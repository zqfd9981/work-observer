"""An investigation remains open as planned experiments become reported observations."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_question_experiment_and_reported_outcome_form_one_journey(tmp_path):
    database = tmp_path / "question-experiments.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = CareerModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成验证岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]

        def create_goal(title):
            return client.post(
                "/api/career",
                headers=auth,
                json={
                    "title": title,
                    "goal": "理解失败处理，并用实际观察检查解释。",
                    "background": "合成本地练习，未在生产环境运行。",
                    "job_ids": [job],
                },
            ).json()["id"]

        identity = create_goal("合成调查与验证闭环")
        base = f"/api/career/{identity}"
        question = client.post(
            base + "/questions",
            headers=auth,
            json={
                "question": "超时重试是否足以解释重复写入？",
                "why_matters": "避免把一次成功观察当成因果证据。",
                "next_evidence": "需要控制请求标识与并发条件。",
            },
        ).json()["questions"][0]
        qid = question["id"]
        task_data = {
            "title": "合成重复写入检查",
            "task_or_ability": "区分超时与并发因素",
            "deliverable": "输入、输出与请求标识",
            "completion_check": "比较正常与超时情境",
            "hypothesis": "重试足以解释重复写入；尚未证实。",
            "question_id": qid,
        }
        manual = client.post(base + "/experiments", headers=auth, json=task_data)
        assert manual.status_code == 201, manual.text
        task = manual.json()["tasks"][0]
        assert not model.contexts
        unobserved = client.post(
            base + "/prepare",
            headers=auth,
            json={
                "kind": "ask",
                "task_id": task["id"],
                "question": question["question"],
            },
        )
        assert unobserved.status_code == 422
        assert not model.contexts
        plan = run_stage(client, identity, auth, "plan", question_id=qid)
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert context["id"] == qid
        assert context["linked_experiments"][0]["state"] == "planned"
        assert not context["linked_experiments"][0]["outcome"]
        step = plan["results"][0]["step_id"]
        imported = client.post(base + "/tasks", headers=auth, json={"step_id": step})
        assert imported.status_code == 200, imported.text
        assert len(imported.json()["tasks"]) == 2
        assert all(row["question_id"] == qid for row in imported.json()["tasks"])
        duplicate = client.post(base + "/tasks", headers=auth, json={"step_id": step})
        assert len(duplicate.json()["tasks"]) == 2
        calls = len(model.contexts)
        observation = "合成观察：正常响应也出现重复写入。尚未控制并发，不能确定原因。"
        reported = client.patch(
            base + f"/tasks/{task['id']}",
            headers=auth,
            json={
                "state": "done",
                "outcome": observation,
                "hypothesis": task_data["hypothesis"],
                "artifact_title": "合成两种情境的运行记录",
                "artifact_text": "合成记录：正常响应write=2，超时重试write=2，未控制并发。",
            },
        )
        assert reported.status_code == 200, reported.text
        saved = reported.json()["tasks"][0]
        assert saved["question_id"] == qid
        assert len(model.contexts) == calls
        assert reported.json()["questions"][0]["state"] == "open"
        reviewed = run_stage(
            client, identity, auth, "ask", task_id=task["id"], question=question["question"]
        )
        latest = reviewed["results"][0]
        assert latest["question_id"] == qid and latest["task_id"] == task["id"]
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert context["selected_experiment_id"] == task["id"]
        assert context["experiments"][0]["reported_observation"] == observation
        assert context["selected_inquiry"]["linked_experiment_count"] == 2
        assert any(
            ev.get("public_document_id") == saved["artifact_document_id"]
            for ev in latest["result"]["evidence"]
        )
        reflected = run_stage(client, identity, auth, "reflect", task_id=task["id"])
        assert reflected["results"][0]["question_id"] == qid
        assert reflected["questions"][0]["state"] == "open"
        assert reflected["questions"][0]["conclusion"] == ""
        # A new check keeps the previous negative observation and the original inquiry.
        calls = len(model.contexts)
        follow_on = client.post(
            base + "/experiments",
            headers=auth,
            json={
                **task_data,
                "title": "合成控制并发后的验证",
                "question_id": None,
                "previous_task_id": task["id"],
                "design_change": "固定请求标识，关闭并发；其余输入保持不变。",
            },
        )
        assert follow_on.status_code == 201, follow_on.text
        child = follow_on.json()["tasks"][-1]
        assert child["previous_task_id"] == task["id"] and child["question_id"] == qid
        assert child["outcome"] == "" and child["state"] == "planned"
        assert len(model.contexts) == calls
        assert follow_on.json()["tasks"][0] == saved
        child_observation = "合成观察：关闭并发后仍重复写入；本次并未确认原因。"
        child = client.patch(
            base + "/tasks/" + child["id"],
            headers=auth,
            json={
                "state": "done",
                "outcome": child_observation,
                "hypothesis": "固定请求标识可能改变重复写入，尚未证实。",
                "design_change": child["design_change"],
                "artifact_title": "合成控制条件后的记录",
                "artifact_text": "合成记录：concurrency=1 request_id=fixed write=2，非线上评测。",
            },
        ).json()["tasks"][-1]
        continued = run_stage(client, identity, auth, "reflect", task_id=child["id"])
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert context["previous_experiment"]["reported_observation"] == observation
        assert context["previous_experiment"]["id"] == task["id"]
        assert context["experiments"][0]["reported_observation"] == child_observation
        assert context["experiments"][0]["design_change"] == child["design_change"]
        assert {
            saved["artifact_document_id"], child["artifact_document_id"]
        } <= {
            ev.get("public_document_id") for ev in continued["results"][0]["result"]["evidence"]
        }
        next_plan = run_stage(client, identity, auth, "plan", task_id=child["id"])
        imported_next = client.post(
            base + "/tasks", headers=auth, json={"step_id": next_plan["results"][0]["step_id"]}
        ).json()["tasks"][-1]
        assert imported_next["previous_task_id"] == child["id"]
        assert imported_next["question_id"] == qid
        # Reuse carries the observation, but a question from another goal is not silently linked.
        other = create_goal("合成另一个目标")
        reused = client.post(
            f"/api/career/{other}/reuse",
            headers=auth,
            json={
                "source_project_id": identity,
                "kind": "task",
                "record_id": child["id"],
            },
        )
        assert reused.status_code == 200, reused.text
        assert reused.json()["tasks"][0]["outcome"] == child_observation
        assert reused.json()["tasks"][0]["question_id"] is None
        assert reused.json()["tasks"][0]["previous_task_id"] is None
        assert client.get(base).json()["tasks"][0] == saved
        invalid = client.post(
            base + "/experiments", headers=auth, json={**task_data, "question_id": "a" * 32}
        )
        assert invalid.status_code == 422
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        data = client.get(base).json()
        assert len(data["tasks"]) == 4 and data["tasks"][0]["question_id"] == qid
        assert data["tasks"][0]["outcome"] == observation
        assert len([row for row in data["results"] if row.get("question_id") == qid]) == 5
