"""The local evidence shelf can reach older records and every original hit."""

import re

import pytest
from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def test_library_pages_records_jobs_and_long_originals_without_model_calls(tmp_path):
    database = tmp_path / "library.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        empty = client.get("/api/career/search", params={"q": "共同检索词"})
        assert empty.status_code == 200, empty.text
        assert empty.json()["records"] == [] and empty.json()["originals"]["evidence"] == []
        jobs = [
            client.post(
                "/api/import",
                headers=auth,
                json={
                    "title": f"合成检索岗位{index}",
                    "company": "合成团队",
                    "description": f"共同检索词 Python接口检查，合成材料编号{index}。",
                    "data_kind": "synthetic",
                },
            ).json()["job_id"]
            for index in range(31)
        ]
        # Raw material remains searchable before the user creates any goal.
        without_goal = client.get("/api/career/search", params={"q": "共同检索词"}).json()
        assert without_goal["scope"] == "all"
        assert without_goal["originals"]["matching_jobs"] == 31
        assert without_goal["records"] == []
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成长期记录检索",
                "goal": "找回较早的实际观察和原文",
                "background": "本地虚构记录。",
                "job_ids": [jobs[0]],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        for index in range(30):
            saved = client.post(
                base + "/insights",
                headers=auth,
                json={
                    "previous_view": "共同检索词：原先只有工具印象。",
                    "observation": "共同检索词：合成观察，不是实际生产验证。",
                    "current_view": f"共同检索词：合成认识{index}。",
                },
            )
            assert saved.status_code == 201
        for index in range(27):
            assert client.post(
                base + "/experiments",
                headers=auth,
                json={
                    "title": f"共同检索词：合成实验{index}",
                    "task_or_ability": "检查输入与输出",
                    "deliverable": "本地记录",
                    "completion_check": "核对观察条件",
                },
            ).status_code == 201
        text = ("共同检索词 " + "合成记录" * 100 + "\n") * 36
        material = client.post(
            base + "/materials", headers=auth, json={"title": "合成长资料", "text": text}
        ).json()["materials"][0]

        before = client.get(base).json()

        def pages(section, *, path=None, **filters):
            result, collected, offset = None, [], 0
            field = "sources_offset" if section == "sources" else "records_offset"
            while True:
                response = client.get(
                    path or base + "/search",
                    params={"q": "共同检索词", field: offset, **filters},
                )
                assert response.status_code == 200, response.text
                result = response.json()
                rows = (
                    result["originals"]["evidence"] if section == "sources" else result["records"]
                )
                collected.extend(rows)
                offset = (
                    result["originals"]["next_offset"]
                    if section == "sources" else result["next_records_offset"]
                )
                if offset is None:
                    return collected, result

        records, _ = pages("records")
        assert len(records) == 57 and len({row["id"] for row in records}) == 57
        insights, filtered = pages("records", record_kind="insight")
        assert len(insights) == 30 and filtered["record_count"] == 30
        assert all(row["kind"] == "insight" for row in insights)
        global_insights, _ = pages(
            "records", path="/api/career/search", record_kind="insight",
        )
        assert {row["id"] for row in global_insights} == {row["id"] for row in insights}
        assert all(row["project_id"] == identity for row in global_insights)
        originals, last = pages("sources", path="/api/career/search")
        assert {row["job_id"] for row in originals if row.get("job_id")} == set(jobs)
        chunks = [row for row in originals if row.get("public_document_id") == material["id"]]
        assert len(chunks) > 20
        assert len({row["id"] for row in originals}) == len(originals)
        assert last["originals"]["evidence_count"] == len(originals)
        assert not last["originals"]["truncated"]
        for row in chunks:
            assert row["quote"] == text[row["start"] : row["end"]]
        scoped, _ = pages("sources")
        assert {row["job_id"] for row in scoped if row.get("job_id")} == {jobs[0]}
        invalid = client.get(
            base + "/search", params={"q": "共同检索词", "records_offset": -1}
        )
        assert invalid.status_code == 422
        for params in ({"q": "共同检索词", "scope": "goal"}, {"q": ""},
                       {"q": "共同检索词", "sources_offset": -1}):
            assert client.get("/api/career/search", params=params).status_code == 422
        assert client.get(base).json() == before
        assert before["usage"]["calls"] == 0
    repository = Repository(database)
    try:
        bounded = UnifiedRetrieval(repository).search(
            ["共同检索词"], limit=20, include_knowledge=False
        )
        assert len(bounded["evidence"]) <= 20
        assert bounded["context_characters"] <= 7000 and bounded["context_limit"] == 7000
    finally:
        repository.close()


def test_library_recalls_names_sources_and_long_terms_with_truthful_previews(tmp_path):
    database = tmp_path / "named-library.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    filename = "synthetic-" + "reading-notes-" * 8 + ".md"
    long_term = "长词开始" + "甲乙丙丁" * 42 + "长词结束"
    text = "合成正文。" * 130 + long_term + "尾部正文关键词，不能证明实际生产能力。"
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def job(title, company):
            response = client.post("/api/import", headers=auth, json={
                "title": title, "company": company, "description": text, "data_kind": "synthetic",
            })
            assert response.status_code == 201, response.text
            return response.json()["job_id"]

        selected = job("合成岗位名称独有词", "合成公司来源独有词")
        other = job("范围外名称独有词", "范围外公司")
        identity = client.post("/api/career", headers=auth, json={
            "title": "合成名称检索", "goal": "找回原文", "background": "本地虚构资料。",
            "job_ids": [selected],
        }).json()["id"]
        base = f"/api/career/{identity}"
        response = client.post(base + "/materials", headers=auth, json={
            "title": filename, "text": text, "source_name": "合成资料来源独有词",
        })
        assert response.status_code == 201, response.text
        document = response.json()["materials"][0]["id"]

        def search(query, **params):
            response = client.get(base + "/search", params={"q": query, **params})
            assert response.status_code == 200, response.text
            return response.json()["originals"]

        for query in ("名称独有词", "公司来源独有词", filename, "资料来源独有词"):
            found = search(query)
            assert found["evidence_count"] == 1
            row = found["evidence"][0]
            assert row["retrieval"]["match_location"] == "metadata"
            assert row["retrieval"]["matched_terms"] == []
            assert row["quote"] == text[:700] and row["start"] == 0
            assert query not in row["quote"]
        assert not search("范围外名称独有词")["evidence"]
        assert search("范围外名称独有词", scope="all")["evidence"][0]["job_id"] == other

        for query in (long_term, "尾部正文关键词"):
            found = search(query)
            assert found["matching_jobs"] == found["matching_public_documents"] == 1
            assert {row.get("job_id") or row.get("public_document_id")
                    for row in found["evidence"]} == {selected, document}
            for row in found["evidence"]:
                assert row["quote"] == text[row["start"]:row["end"]]
                assert query in row["quote"] and row["start"] > 0
                assert row["retrieval"]["match_location"] == "body"
                assert row["retrieval"]["matched_terms"] == [query]
        assert client.get(base).json()["usage"]["calls"] == 0

    repository = Repository(database)
    try:
        # A library name hit must not become a body citation in model retrieval.
        service = UnifiedRetrieval(repository)
        assert not service.search(
            ["名称独有词"], job_ids=[selected], public_document_ids=[document],
            include_knowledge=False,
        )["evidence"]
        with pytest.raises(ProbeError, match="INVALID_SEARCH_TERMS"):
            service.search([filename], include_knowledge=False)
    finally:
        repository.close()
