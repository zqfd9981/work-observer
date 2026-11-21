"""Capture exact archived passages into chosen inquiries without model calls."""

import re

from starlette.testclient import TestClient

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


def test_capture_creates_and_appends_inquiries_without_calls(tmp_path, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Capturing a passage must not start research")

    monkeypatch.setattr(ModelClient, "turn", forbidden)
    database = tmp_path / "capture.db"
    upgrade(database)
    with TestClient(create_app(
        Settings(database_path=database, raw_directory=tmp_path / "raw"),
    ), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, payload, method="post"):
            response = getattr(client, method)(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        quote = "🧪" * 240 + "末尾限定：只说明局部观察，实际生产权限未知。"
        text = "前言🙂" + chr(13) + chr(10) + quote + chr(13) + chr(10) + "重复段落：" + quote
        origin = post("/api/career", {
            "title": "合成原资料目标", "goal": "保留原资料", "material_text": text,
            "material_title": "<合成原文>", "background": "来源目标的个人背景。",
        })
        document = origin["materials"][0]["id"]
        start = text.rindex(quote)
        passage = {"public_document_id": document, "start": start, "end": start + len(quote)}
        original_before = client.get("/api/career/" + origin["id"]).json()
        full_question = "理解这些条件。" * 160 + "末尾问题：怎样区分局部与生产责任？"
        captured = post("/api/career/capture-passage", {
            "passage": passage, "question": full_question, "goal_title": "合成新调查",
            "user_note": "需要用反例区分适用范围。",
        })
        target = "/api/career/" + captured["id"]
        qid = captured["captured_question_id"]
        question = next(q for q in captured["questions"] if q["id"] == qid)
        assert captured["created_goal"] and question["question"] == full_question
        assert question["source_passage"]["quote"] == quote
        assert question["source_passage"]["start"] == start
        assert question["material_ids"] == [document]
        assert question["hypothesis_a"] == question["hypothesis_b"] == ""
        assert captured["document_ids"] == [document]
        assert captured["focus_question_id"] == qid
        assert (captured["profile"] or {}).get("background", "") == ""
        assert not captured["results"] and captured["usage"]["calls"] == 0
        answered = post(target + "/questions/" + qid, {
            "question": full_question, "state": "answered", "conclusion": "已有结论仍有条件限制。",
            "material_ids": [document],
        }, method="patch")
        other = post(target + "/questions", {"question": "另一个正在关注的问题。"})
        other_id = other["questions"][-1]["id"]
        response = client.patch(target + "/focus", headers=auth, json={"question_id": other_id})
        assert response.status_code == 200
        appended = post("/api/career/capture-passage", {
            "goal_id": captured["id"], "question_id": qid, "passage": passage,
            "relation": "conditions", "user_note": "补充局部观察条件。",
            "target_view": "原结论中的责任解释。",
        })
        changed = next(q for q in appended["questions"] if q["id"] == qid)
        prior = next(q for q in answered["questions"] if q["id"] == qid)
        preserved = {key: value for key, value in prior.items()
                     if key not in {"updated_at", "evidence_passages"}}
        assert {key: changed[key] for key in preserved} == preserved
        collected = changed["evidence_passages"][-1]
        assert collected["quote"] == quote and collected["relation"] == "conditions"
        assert collected["target_view"] == "原结论中的责任解释。"
        assert appended["focus_question_id"] == other_id
        assert appended["document_ids"].count(document) == 1
        excerpt_only = post("/api/career/capture-passage", {
            "passage": passage, "question": "先保留这条线索？", "include_source": False,
        })
        assert excerpt_only["document_ids"] == []
        assert excerpt_only["questions"][0]["source_passage"]["quote"] == quote
        assert excerpt_only["questions"][0]["material_ids"] == []
        jobs = [post("/api/import", {
            "title": "合成JD" + str(index), "company": "合成团队", "description": text,
            "data_kind": "synthetic",
        }) for index in range(7)]
        source_job = client.get("/api/jobs/" + jobs[0]["job_id"]).json()
        job_document = source_job["provenance"]["description_text"]["document_id"]
        catalog = client.get("/api/sources/" + job_document).json()
        version = next(v for v in catalog["versions"] if v["kind"] == "detail")
        jd_passage = {"document_id": job_document,
                      "snapshot_id": version["snapshot_id"], "start": start,
                      "end": start + len(quote)}
        destination_before = client.get(target).json()
        jd = post("/api/career/capture-passage", {
            "goal_id": captured["id"], "passage": jd_passage, "question": "岗位责任有什么边界？",
        })
        assert [row["id"] for row in jd["jobs"]] == [jobs[0]["job_id"]]
        assert jd["questions"][-1]["source_passage"]["snapshot_id"] == version["snapshot_id"]
        assert jd["questions"][-1]["source_passage"]["quote"] == quote
        assert jd["profile"] == destination_before["profile"]
        assert jd["focus_question_id"] == other_id
        limited = post("/api/career", {
            "title": "合成六岗位目标", "goal": "核对责任",
            "job_ids": [j["job_id"] for j in jobs[1:]],
        })
        limited_before = client.get("/api/career/" + limited["id"]).json()
        refused = client.post("/api/career/capture-passage", headers=auth, json={
            "goal_id": limited["id"], "passage": jd_passage, "question": "另一个岗位如何解释？",
        })
        assert refused.status_code == 422
        assert client.get("/api/career/" + limited["id"]).json() == limited_before
        listing_before = client.get("/api/career").json()
        for payload in (
            {"passage": {**passage, "end": len(text) + 1}, "question": "无效位置？"},
            {"passage": passage, "question": ""},
            {"passage": passage, "goal_id": captured["id"], "question_id": "f" * 32},
            {"passage": passage, "question_id": qid},
        ):
            invalid = client.post("/api/career/capture-passage", headers=auth, json=payload)
            assert invalid.status_code == 422, invalid.text
        assert client.get("/api/career").json() == listing_before
        assert client.get("/api/career/" + origin["id"]).json() == original_before
