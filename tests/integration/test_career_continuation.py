"""Following a discussion keeps its real focus, while explicit clearing is respected."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_following_a_discussion_keeps_full_records_and_can_start_independently(tmp_path):
    database = tmp_path / "continuation.db"
    upgrade(database)
    model = CareerModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成续问岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成连续调查",
                "goal": "保留具体观察和限制",
                "background": "本地合成练习。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        question = client.post(
            base + "/questions", headers=auth, json={"question": "重试能解释重复写入吗？"}
        ).json()["questions"][0]
        design = {
            "title": "合成样本",
            "task_or_ability": "区分失败原因",
            "deliverable": "双组记录",
            "completion_check": "核对请求与写入",
            "question_id": question["id"],
        }
        tasks = [
            client.post(
                base + "/experiments", headers=auth, json={**design, "title": f"合成样本{i}"}
            ).json()["tasks"][-1]
            for i in range(4)
        ]
        observation = "合成观察。" * 160 + "末尾限制：未控制并发，没有生产效果证据。"
        task = client.patch(
            base + "/tasks/" + tasks[0]["id"],
            headers=auth,
            json={
                "state": "done",
                "outcome": observation,
                "artifact_title": "合成运行记录",
                "artifact_text": "normal writes=2; timeout writes=2; 尚未控制并发。",
            },
        ).json()["tasks"][0]
        for other in tasks[1:]:
            client.patch(
                base + "/tasks/" + other["id"],
                headers=auth,
                json={"state": "done", "outcome": "合成另一个样本的短观察。"},
            )
        tasks.append(
            client.post(
                base + "/experiments",
                headers=auth,
                json={**design, "title": "合成尚未执行的设计"},
            ).json()["tasks"][-1]
        )
        note = client.post(
            base + "/insights",
            headers=auth,
            json={
                "previous_view": "重试就能解决。",
                "observation": "正常响应也重复写入。",
                "current_view": "原解释不足，尚需区分原因。",
                "task_id": task["id"],
            },
        ).json()["insights"][0]
        client.post(
            base + f"/insights/{note['id']}/use", headers=auth, json={"use_for_research": False}
        )
        material = client.post(
            base + "/materials",
            headers=auth,
            json={"title": "合成补充", "text": "仅为虚构记录，不能证明企业责任。"},
        ).json()["materials"][0]
        parent = run_stage(
            client,
            identity,
            auth,
            "ask",
            question=question["question"],
            question_id=question["id"],
            task_id=task["id"],
            insight_id=note["id"],
            material_id=material["id"],
        )["results"][0]
        child = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="接着检查末尾限制。",
            source_step_id=parent["step_id"],
        )["results"][0]
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert child["question_id"] == question["id"] and child["task_id"] == task["id"]
        assert child["insight_id"] == note["id"] and child["material_id"] == material["id"]
        assert context["experiments"][0]["reported_observation"] == observation
        assert context["selected_learning_note"]["use_for_research"] is False
        assert context["selected_inquiry"]["id"] == question["id"]
        assert context["selected_material"]["document_id"] == material["id"]
        fresh = client.post(
            base + "/materials",
            headers=auth,
            json={"title": "合成新反例", "text": "新观察仍未确认因果。"},
        ).json()["materials"][-1]
        changed = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="结合新反例继续。",
            source_step_id=child["step_id"],
            material_id=fresh["id"],
        )["results"][0]
        assert changed["material_id"] == fresh["id"] and changed["task_id"] == task["id"]
        independent = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="不沿用旧重点。",
            source_step_id=child["step_id"],
            inherit_focus=False,
        )["results"][0]
        assert all(
            independent[key] is None
            for key in ("question_id", "task_id", "insight_id", "material_id")
        )
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert context["selected_inquiry"] is None and context["selected_experiment_id"] is None
        unbound = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="只查实验，暂不绑定清单问题。",
            task_id=task["id"],
            inherit_focus=False,
        )["results"][0]
        assert unbound["question_id"] is None and unbound["task_id"] == task["id"]
        other_question = client.post(
            base + "/questions", headers=auth, json={"question": "另一个待研究的问题。"}
        ).json()["questions"][-1]
        redirected = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="只把旧分析作为参考。",
            source_step_id=child["step_id"],
            question_id=other_question["id"],
        )["results"][0]
        assert redirected["question_id"] == other_question["id"]
        assert redirected["task_id"] is None and redirected["insight_id"] is None
        pair = [parent["step_id"], child["step_id"]]
        compared = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="比较两次判断。",
            question_id=question["id"],
            comparison_step_ids=pair,
        )["results"][0]
        continued = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="接着核对这两次。",
            source_step_id=compared["step_id"],
        )["results"][0]
        assert continued["comparison_step_ids"] == pair
        planned = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="这份实验设计还缺什么？",
            task_id=tasks[-1]["id"],
        )["results"][0]
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert planned["task_id"] == tasks[-1]["id"]
        assert context["experiments"][0]["state"] == "planned"
        assert context["experiments"][0]["reported_observation"] == ""
        assert "不能补造执行结果" in model.contexts[-1]["question"]
        story = client.post(
            base + "/stories",
            headers=auth,
            json={
                "title": "合成个人经历",
                "situation": "排查本地失败",
                "action": "我只构造了输入。",
                "result": "尚未确认原因。",
                "limits": "未参与生产部署。",
            },
        ).json()["stories"][0]
        interviewed = run_stage(client, identity, auth, "interview", story_id=story["id"])[
            "results"
        ][0]
        asked = run_stage(
            client,
            identity,
            auth,
            "ask",
            question="这份经历怎样表述边界？",
            source_step_id=interviewed["step_id"],
        )["results"][0]
        assert asked["story_id"] == story["id"]
        assert any(
            ev.get("public_document_id") == story["document_id"]
            for ev in asked["result"]["evidence"]
        )
        assert client.get(base).json()["questions"][0]["state"] == "open"
