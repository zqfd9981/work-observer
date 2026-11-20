"""The local evidence shelf can reach older records and every original hit."""

import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
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

        def pages(section, **filters):
            result, collected, offset = None, [], 0
            field = "sources_offset" if section == "sources" else "records_offset"
            while True:
                response = client.get(
                    base + "/search",
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
        originals, last = pages("sources", scope="all")
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
        assert client.get(base).json()["usage"]["calls"] == 0
    repository = Repository(database)
    try:
        bounded = UnifiedRetrieval(repository).search(
            ["共同检索词"], limit=20, include_knowledge=False
        )
        assert len(bounded["evidence"]) <= 20
        assert bounded["context_characters"] <= 7000 and bounded["context_limit"] == 7000
    finally:
        repository.close()
