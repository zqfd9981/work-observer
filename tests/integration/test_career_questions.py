"""A saved unknown survives source additions and multiple locally simulated investigations."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_question_tracks_investigations_and_user_conclusion(tmp_path):
    database = tmp_path / "questions.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        auth = {"X-WO-Token": token}
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成接口岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成持续调查",
                "goal": "理解接口工作的验收方式",
                "background": "合成本地练习",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        role = run_stage(client, identity, auth, "role")
        source_id = role["results"][0]["step_id"]
        calls = len(model.contexts)
        question_data = {
            "question": "失败样例验证在这个岗位如何验收？",
            "why_matters": "决定工作样本需要展示哪些产物。",
            "next_evidence": "需要实际验收说明，而不只是一句工具要求。",
            "source_step_id": source_id,
        }
        saved = client.post(base + "/questions", json=question_data, headers=auth)
        assert saved.status_code == 201, saved.text
        question = saved.json()["questions"][0]
        qid = question["id"]
        assert len(model.contexts) == calls
        first = run_stage(
            client, identity, auth, "ask", question=question["question"], question_id=qid
        )
        first_step = first["results"][0]["step_id"]
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert context["why_matters"] == question["why_matters"]
        assert context["next_evidence"] == question["next_evidence"]
        assert context["earlier_discussions"] == []
        assert (
            first["questions"][0]["state"] == "open"
        )  # A completed model answer is not resolution.
        material = client.post(
            base + "/materials",
            headers=auth,
            json={
                "title": "合成验收调查记录",
                "text": "合成观察：应检查失败输入与运行输出，企业验收标准仍未知。",
            },
        )
        assert material.status_code == 201, material.text
        material_id = material.json()["materials"][0]["id"]
        second = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="结合新增记录，哪些判断仍需保留未知？",
            question_id=qid,
            material_id=material_id,
        )
        second_step = second["results"][0]["step_id"]
        context = model.contexts[-1]["project_context"]["career_evidence"]
        inquiry = context["selected_inquiry"]
        assert len(inquiry["earlier_discussions"]) == 1
        assert inquiry["earlier_discussions"][0]["claims_to_recheck"]
        assert "重读" in inquiry["history_notice"]
        assert context["selected_material"]["document_id"] == material_id
        assert [row["question_id"] for row in second["results"][:2]] == [qid, qid]
        assert first_step != second_step
        assert second["questions"][0]["state"] == "open"

        missing = client.patch(
            base + f"/questions/{qid}", headers=auth, json={**question_data, "state": "answered"}
        )
        assert missing.status_code == 422
        calls = len(model.contexts)
        conclusion = "当前材料仅能支持设计失败输入输出检查，尚不知道企业的实际验收口径。"
        finished = client.patch(
            base + f"/questions/{qid}",
            headers=auth,
            json={
                **question_data,
                "state": "answered",
                "conclusion": conclusion,
                "conclusion_step_id": second_step,
            },
        )
        assert finished.status_code == 200, finished.text
        assert len(finished.json()["questions"]) == 1
        assert len(model.contexts) == calls
        listing = client.get("/api/career").json()
        assert next(row for row in listing if row["id"] == identity)["open_question_count"] == 0
        found = client.get(base + "/search", params={"q": "验收口径"}).json()
        assert any(row["kind"] == "question" and row["id"] == qid for row in found["records"])
        # Rechecking an answered question retains the user's decision and full limitation.
        rechecked = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="对照我选的两次研究，重新核实这个口径。",
            question_id=qid,
            comparison_step_ids=[second_step, first_step],
        )
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert context["conclusion"] == conclusion and len(context["earlier_discussions"]) == 2
        assert context["comparison_requested"] is True
        assert [row["step_id"] for row in context["earlier_discussions"]] == [
            second_step,
            first_step,
        ]
        assert all(row["source_references_to_reread"] for row in context["earlier_discussions"])
        assert all(
            row["claim_details_to_recheck"][0]["requirement"] == "required"
            for row in context["earlier_discussions"]
        )
        assert rechecked["results"][0]["comparison_step_ids"] == [second_step, first_step]
        assert rechecked["questions"][0]["state"] == "answered"
        calls = len(model.contexts)
        for selected in ([first_step], [first_step, first_step], [first_step, source_id]):
            invalid_comparison = client.post(
                base + "/prepare",
                headers=auth,
                json={
                    "kind": "ask",
                    "question": "对照两次。",
                    "question_id": qid,
                    "comparison_step_ids": selected,
                },
            )
            assert invalid_comparison.status_code == 422, invalid_comparison.text
        assert len(model.contexts) == calls
        parked = client.patch(
            base + f"/questions/{qid}",
            headers=auth,
            json={
                **question_data,
                "state": "parked",
                "conclusion": conclusion,
                "conclusion_step_id": second_step,
            },
        )
        assert parked.status_code == 200
        invalid = client.post(
            base + "/prepare",
            headers=auth,
            json={"kind": "ask", "question": "问错目标。", "question_id": "a" * 32},
        )
        assert invalid.status_code == 422
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        data = client.get(base).json()
        assert data["questions"][0]["state"] == "parked"
        assert data["questions"][0]["conclusion"] == conclusion
        assert len([row for row in data["results"] if row.get("question_id") == qid]) == 3
