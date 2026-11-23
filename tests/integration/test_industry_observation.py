"""Industry findings must stay anchored to archived text, without model calls."""

import copy
import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.collection.contracts import Capture, WatchsetSpec, now
from work_observer.config import Settings
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def test_observation_evidence_scope_and_followup(tmp_path):
    database = tmp_path / "industry.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    repository = Repository(database)
    run = repository.begin_run("合成摘要", WatchsetSpec(query="合成", city="未知"), "replay")
    stamp = now()
    record = {"job_id": "list-only", "title": "仅有标题的岗位"}
    capture = Capture(raw={"job": record}, request={}, observed_at=stamp,
                      provenance={"origin": "test", "transport": "mcp"})
    path, sha = RawArchive(settings.raw_directory).save(capture.raw)
    document = repository.document(run, "list", capture, path, sha)
    step = repository.start_step(run, "pages", 1)
    repository.page(run, "boss", 1, [record], {}, document, stamp, step)
    repository.finish(run, "success", "fixture", False, False)
    missing_id = repository.jobs()[0]["id"]
    repository.close()
    with TestClient(create_app(settings, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        page = client.get("/").text
        headers = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', page)[1]}
        assert 'id="page-industry"' in page
        assert client.get("/assets/industry.js").status_code == 200
        jobs = []
        for key, text in (("a", "负责业务接口开发，Python或Java一种语言。"),
                          ("b", "负责企业知识库检索，需独立交付应用。")):
            result = client.post("/api/import", headers=headers, json={
                "title": "合成观察岗位", "company": "合成公司", "external_id": key,
                "description": text, "data_kind": "synthetic",
            })
            assert result.status_code == 201, result.text
            jobs.append(result.json()["job_id"])
        data = dict(title="合成工作分工观察", question="应用开发工作有什么区别？",
                    summary="接口和知识库工作在不同岗位出现，不能据此推断市场占比。",
                    job_ids=jobs + [missing_id], findings=[dict(
                        title="业务接口是一条工作线", facet="work", basis="synthesis",
                        interpretation="第一份资料描述接口开发。", boundary="仅限此样本。",
                        evidence=[dict(job_id=jobs[0],
                                       quote="负责业务接口开发，Python或Java一种语言。",
                                       role="职责与语言选择")],
                    )], unknowns=["没有连续时间样本。"], next_questions=["交付标准是什么？"])
        for invalid in (dict(quote="原文中不存在的任意一句话"), dict(job_id="f" * 32),
                        dict(job_id=missing_id)):
            bad = copy.deepcopy(data)
            bad["findings"][0]["evidence"][0].update(invalid)
            assert client.post("/api/industry", headers=headers, json=bad).status_code == 422
        assert client.get("/api/industry").json() == []
        saved = client.post("/api/industry", headers=headers, json=data)
        assert saved.status_code == 201, saved.text
        report = saved.json()
        identity = report["id"]
        assert report["origin"] == "assisted_analysis"
        assert report["sample"]["jobs"] == 3
        assert report["sample"]["readable_details"] == 2
        assert report["sample"]["missing_details"] == 1
        assert report["sample"]["cited_jobs"] == 1
        assert all(s["availability"] == "verified" for s in report["sources"] if s["has_detail"])
        ev = report["findings"][0]["evidence"][0]
        assert ev["start"] == 0 and ev["end"] == len(ev["quote"])
        inquiry = client.post(f"/api/industry/{identity}/inquiries", headers=headers,
                              json={"finding_index": 0, "question": "接口交付的验收是什么？"})
        assert inquiry.status_code == 201, inquiry.text
        linked = inquiry.json()
        assert linked["started"] is False and linked["job_ids"] == jobs[:1]
        project = client.get("/api/projects/" + linked["project_id"]).json()
        assert project["job_ids"] == jobs[:1] and project["budget"]["max_public"] == 0
        assert project["steps"][0]["state"] == "queued"
        assert "接口交付的验收是什么" in project["goal"]
        assert "辅助分析，不是独立证据" in project["goal"]
        assert client.post(f"/api/industry/{identity}/inquiries", headers=headers,
                           json={"finding_index": 9, "question": "其他工作？"}).status_code == 422
        # New current content does not silently rewrite the saved observation's evidence.
        changed = client.post("/api/import", headers=headers, json={
            "title": "合成观察岗位", "company": "合成公司", "external_id": "a",
            "description": "新职责：负责不同的文档管理工作。", "data_kind": "synthetic",
        })
        assert changed.status_code == 201
        old = client.get("/api/industry/" + identity).json()
        assert old["findings"][0]["interpretation"] == report["findings"][0]["interpretation"]
        assert old["findings"][0]["needs_review"] is True
        assert old["evolution"]["changes"][0]["kind"] == "正文内容已变化"
        assert all(s["availability"] == "verified" for s in old["sources"] if s["has_detail"])
        assert "IndustryObservationInput" in client.get("/api/openapi.json").text
        correction = dict(
            finding_index=0, decision="revise", reason="回读新原文，工作职责已不同。",
            interpretation="当前岗位改为文档管理工作。", boundary="仅限这个已有岗位。",
            evidence=[dict(job_id=jobs[0], quote="新职责：负责不同的文档管理工作。")],
            next_question="文档管理工作的交付和验收要求是什么？",
        )
        bad = copy.deepcopy(correction)
        bad["evidence"][0]["quote"] = "无法从原文核对的虚构文本"
        assert client.post(f"/api/industry/{identity}/revisions", headers=headers,
                           json=bad).status_code == 422
        assert client.get("/api/industry/" + identity).json()["evolution"]["revisions"] == 0
        revised = client.post(f"/api/industry/{identity}/revisions", headers=headers,
                              json=correction)
        assert revised.status_code == 201, revised.text
        updated = revised.json()
        finding = updated["findings"][0]
        assert finding["needs_review"] is False and finding["decision"] == "revise"
        assert finding["history"][0]["previous_interpretation"] == "第一份资料描述接口开发。"
        assert finding["evidence"][0]["source"]["document_id"] != ev["source"]["document_id"]
        assert updated["evolution"]["revisions"] == 1
        # This remains source change since the initial observation, not a market trend claim.
        assert updated["evolution"]["changes"][0]["kind"] == "正文内容已变化"
        followup = client.post(f"/api/industry/{identity}/inquiries", headers=headers,
                               json={"question": "继续检查已知纠正及缺正文岗位。"}).json()
        assert set(followup["job_ids"]) == set(jobs + [missing_id])
        project = client.get("/api/projects/" + followup["project_id"]).json()
        assert correction["reason"] in project["goal"]
        assert correction["interpretation"] in project["goal"]
        bad = {**correction, "decision": "retain", "interpretation": "又改了判断"}
        assert client.post(f"/api/industry/{identity}/revisions", headers=headers,
                           json=bad).status_code == 422
        for decision in ("withdraw", "unresolved", "retain"):
            response = client.post(f"/api/industry/{identity}/revisions", headers=headers,
                                   json={**correction, "decision": decision})
            assert response.status_code == 201, response.text
            assert response.json()["findings"][0]["decision"] == decision
    with TestClient(create_app(settings, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        restored = client.get("/api/industry/" + identity).json()
        assert restored["evolution"]["revisions"] == 4
        assert len(restored["evolution"]["inquiries"]) == 2
        assert restored["findings"][0]["history"][0]["previous_decision"] == "initial"
        assert restored["findings"][0]["initial_interpretation"] == "第一份资料描述接口开发。"
