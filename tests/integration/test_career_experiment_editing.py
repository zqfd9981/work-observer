"""Turn a suggested experiment into a user's runnable plan while retaining its origin."""

import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


def test_edited_plan_is_used_in_research_without_rewriting_its_original_suggestion(tmp_path):
    database = tmp_path / "editable-experiments.db"
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
                "title": "合成实验编辑岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成可执行实验",
                "goal": "将建议改成自己的检查方法",
                "background": "本地虚构练习，未做生产验证。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        question = client.post(
            base + "/questions",
            headers=auth,
            json={
                "question": "超时重试能否解释重复写入？",
            },
        ).json()["questions"][0]
        planned = run_stage(client, identity, auth, "plan", question_id=question["id"])
        source = planned["results"][0]
        original_plan = source["result"]["application_plan"]
        task = client.post(
            base + "/tasks",
            headers=auth,
            json={
                "step_id": source["step_id"],
            },
        ).json()["tasks"][0]
        calls = len(model.contexts)
        design = {
            "title": "合成：固定请求标识后做三组对照",
            "task_or_ability": "区分超时、并发与重复提交",
            "deliverable": "每组输入、请求标识、返回状态和写入条数",
            "completion_check": "正常响应、超时重试和关闭并发各重复十次，保留失败记录。",
        }
        response = client.patch(
            base + "/tasks/" + task["id"],
            headers=auth,
            json={
                "state": "planned",
                **design,
            },
        )
        assert response.status_code == 200, response.text
        edited = response.json()["tasks"][0]
        assert all(edited[key] == value for key, value in design.items())
        assert edited["question_id"] == question["id"] and edited["state"] == "planned"
        assert edited["source_key"] == task["source_key"]
        assert not edited["outcome"] and len(model.contexts) == calls
        # Importing the original suggestion again must leave the user's adjustments in place.
        imported = client.post(
            base + "/tasks",
            headers=auth,
            json={
                "step_id": source["step_id"],
            },
        ).json()
        assert imported["tasks"] == response.json()["tasks"]
        assert imported["results"][0]["result"]["application_plan"] == original_plan

        observation = "合成观察：正常响应与超时情境均出现重复写入；原因仍未知。"
        reported = client.patch(
            base + "/tasks/" + task["id"],
            headers=auth,
            json={
                "state": "done",
                "outcome": observation,
                "artifact": "本地合成日志",
                "artifact_text": "合成记录：正常响应 write=2；超时重试 write=2；未做生产测试。",
            },
        ).json()
        current = reported["tasks"][0]
        assert all(current[key] == value for key, value in design.items())
        assert current["outcome"] == observation and len(model.contexts) == calls
        invalid = client.patch(
            base + "/tasks/" + task["id"],
            headers=auth,
            json={
                "state": "done",
                "outcome": observation,
                "title": "   ",
                "artifact_text": "不应因无效计划写入的另一份合成记录。",
            },
        )
        assert invalid.status_code == 422
        unchanged = client.get(base).json()
        assert unchanged["tasks"][0] == current
        assert unchanged["document_ids"] == reported["document_ids"]

        reviewed = run_stage(
            client,
            identity,
            auth,
            "ask",
            task_id=task["id"],
            question="按我修改后的检查方法分析这次实际观察。",
        )
        experiment = model.contexts[-1]["project_context"]["career_evidence"]["experiments"][0]
        assert experiment["title"] == design["title"]
        assert experiment["planned_deliverable"] == design["deliverable"]
        assert experiment["proposed_check"] == design["completion_check"]
        assert experiment["reported_observation"] == observation
        assert reviewed["results"][0]["question_id"] == question["id"]
        old = next(row for row in reviewed["results"] if row["step_id"] == source["step_id"])
        assert old["result"]["application_plan"] == original_plan

    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        reopened = client.get(base).json()["tasks"][0]
        assert all(reopened[key] == value for key, value in design.items())
        assert reopened["outcome"] == observation
