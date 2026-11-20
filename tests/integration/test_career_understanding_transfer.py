"""Past understanding is transferred as a question, never as an adopted fact."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_understanding_and_questions_transfer_without_adopting_old_conclusions(tmp_path):
    database = tmp_path / "understanding-transfer.db"
    upgrade(database)
    model = CareerModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        jobs = [
            client.post(
                "/api/import",
                headers=auth,
                json={
                    "title": "合成" + name,
                    "company": "合成团队",
                    "data_kind": "synthetic",
                    "external_id": name,
                    "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
                },
            ).json()["job_id"]
            for name in ("旧应用岗位", "新平台岗位")
        ]

        def goal(title, job):
            return client.post(
                "/api/career",
                headers=auth,
                json={
                    "title": title,
                    "goal": "核对理解的适用条件",
                    "background": "合成本地经历。",
                    "job_ids": [job],
                },
            ).json()["id"]

        source, target = goal("合成旧目标", jobs[0]), goal("合成新目标", jobs[1])
        note_data = {
            "previous_view": "知道工具名就能说明能力。",
            "observation": "合成实际观察。" * 140 + "限定：这些观察来自本地练习。",
            "current_view": "合成工作理解。" * 150 + "结尾限定：迁移边界不等于能力缺失。",
            "open_question": "这套理解是否适用于新岗位的实际任务？",
        }
        saved = client.post(f"/api/career/{source}/insights", headers=auth, json=note_data)
        assert saved.status_code == 201, saved.text
        note = saved.json()["insights"][0]
        original = client.post(
            f"/api/career/{source}/insights/{note['id']}/use",
            headers=auth,
            json={"use_for_research": False},
        ).json()["insights"][0]
        payload = {"source_project_id": source, "kind": "insight", "record_id": note["id"]}
        transferred = client.post(f"/api/career/{target}/reuse", headers=auth, json=payload)
        assert transferred.status_code == 200, transferred.text
        inquiry = transferred.json()["questions"][0]
        qid = inquiry["id"]
        assert inquiry["state"] == "open" and inquiry["conclusion"] == ""
        assert inquiry["source_step_id"] is None and inquiry["conclusion_step_id"] is None
        carried = inquiry["carried_understanding"]
        assert carried["understanding"] == note_data["current_view"]
        assert carried["observation"] == note_data["observation"]
        assert carried["was_in_use"] is False
        assert transferred.json()["document_ids"] == []
        assert not transferred.json()["insights"] and not model.contexts
        duplicate = client.post(f"/api/career/{target}/reuse", headers=auth, json=payload).json()
        assert len(duplicate["questions"]) == 1 and duplicate["questions"][0]["id"] == qid
        assert client.get(f"/api/career/{source}").json()["insights"][0] == original
        found = client.get(
            f"/api/career/{target}/search", params={"q": "边界不等于能力缺失"}
        ).json()
        assert any(row["kind"] == "question" and row["id"] == qid for row in found["records"])
        edited = client.patch(
            f"/api/career/{target}/questions/{qid}",
            headers=auth,
            json={
                "question": "在当前平台岗位中，哪些理解还需要新的依据？",
                "why_matters": "合成调查：避免把旧经历直接套在新岗位。",
                "state": "open",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["questions"][0]["carried_understanding"] == carried
        checked = run_stage(
            client, target, auth, "ask", question=inquiry["question"], question_id=qid
        )
        context = model.contexts[-1]
        assert [row["id"] for row in context["fixed_scope"]["jobs"]] == [jobs[1]]
        personal = context["project_context"]["career_evidence"]
        assert personal["selected_inquiry"]["carried_understanding"] == carried
        assert personal["learning_notes"] == []
        assert (
            checked["questions"][0]["state"] == "open"
            and checked["questions"][0]["conclusion"] == ""
        )
        assert client.get(f"/api/career/{source}").json()["insights"][0] == original
        old_question = client.post(
            f"/api/career/{source}/questions",
            headers=auth,
            json={
                "question": "旧目标的验收口径是什么？",
                "state": "answered",
                "conclusion": "旧目标下保存的个人结论，尚未独立核实。",
            },
        ).json()["questions"][0]
        copied_question = client.post(
            f"/api/career/{target}/reuse",
            headers=auth,
            json={
                "source_project_id": source,
                "kind": "question",
                "record_id": old_question["id"],
            },
        ).json()["questions"][-1]
        assert copied_question["state"] == "open" and copied_question["conclusion"] == ""
        assert (
            copied_question["carried_understanding"]["understanding"] == old_question["conclusion"]
        )
        assert client.get(f"/api/career/{source}").json()["questions"][0] == old_question
        third = goal("合成第三个目标", jobs[1])
        carried_again = client.post(
            f"/api/career/{third}/reuse",
            headers=auth,
            json={
                "source_project_id": target,
                "kind": "question",
                "record_id": qid,
            },
        ).json()["questions"][0]
        assert carried_again["carried_understanding"]["understanding"] == note_data["current_view"]
        assert carried_again["carried_understanding"]["was_in_use"] is False
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        questions = client.get(f"/api/career/{target}").json()["questions"]
        assert len(questions) == 2 and all(row["state"] == "open" for row in questions)
        assert questions[0]["carried_understanding"] == carried
