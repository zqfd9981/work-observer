"""A chosen older project stays selected through questions, answers and followups."""

import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


@pytest.mark.parametrize("focus", ["story", "task"])
def test_interview_retains_chosen_material_and_full_observations(tmp_path, focus):
    database = tmp_path / "interview.db"
    upgrade(database)
    model = CareerModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成项目面试岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成指定项目面试",
                "goal": "如实讲清个人参与、失败观察和限制",
                "background": "只做过本地练习，尚无生产效果数据。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        for index in range(4):
            story = client.post(
                base + "/stories",
                headers=auth,
                json={
                    "title": f"合成经历{index}",
                    "situation": "本地接口重复提交检查",
                    "action": "我构造样例并记录输出，没有负责线上部署。",
                    "result": "样例可运行，但未证明生产效果。",
                    "limits": "只在合成环境观察。" * 50 + "结尾限定：未参与业务验收。",
                },
            ).json()["stories"][-1]
            task = client.post(
                base + "/experiments",
                headers=auth,
                json={
                    "title": f"合成样本{index}",
                    "task_or_ability": "检验重复写入原因",
                    "deliverable": "本地双组运行记录",
                    "completion_check": "核对请求标识和写入次数",
                },
            ).json()["tasks"][-1]
            outcome = "合成观察：两组都发生重复写入。" * 45 + "末尾：尚未区分并发与超时。"
            task = client.patch(
                base + "/tasks/" + task["id"],
                headers=auth,
                json={
                    "state": "done",
                    "outcome": outcome,
                    "hypothesis": "合成原预期。" * 80 + "末尾：只有超时导致重复写入。",
                    "artifact_title": f"合成日志{index}",
                    "artifact_text": "normal writes=2; timeout writes=2; 未独立验证线上效果。",
                },
            ).json()["tasks"][-1]
            if index == 0:
                selected_story, selected_task = story, task
        record = selected_story if focus == "story" else selected_task
        key = focus + "_id"
        document = record["document_id" if focus == "story" else "artifact_document_id"]
        invalid = client.post(
            base + "/prepare", headers=auth, json={"kind": "interview", key: "0" * 32}
        )
        assert invalid.status_code == 422
        ambiguous = client.post(
            base + "/prepare",
            headers=auth,
            json={
                "kind": "interview",
                "story_id": selected_story["id"],
                "task_id": selected_task["id"],
            },
        )
        assert ambiguous.status_code == 422
        assert not model.contexts

        def check(data):
            row = data["results"][0]
            context = model.contexts[-1]["project_context"]["career_evidence"]
            assert row[key] == record["id"]
            assert any(
                ev.get("public_document_id") == document for ev in row["result"]["evidence"]
            )
            if focus == "story":
                assert context["selected_story"]["id"] == record["id"]
                assert [item["title"] for item in context["stories"]] == [record["title"]]
                assert context["experiments"] == []
            else:
                assert context["stories"] == []
                assert context["selected_experiment_id"] == record["id"]
                assert len(context["experiments"]) == 1
                assert context["experiments"][0]["reported_observation"] == outcome
                assert context["experiments"][0]["prior_expectation"].endswith(
                    "只有超时导致重复写入。"
                )
            return row

        questions = check(run_stage(client, identity, auth, "interview", **{key: record["id"]}))
        answer = check(
            run_stage(
                client,
                identity,
                auth,
                "answer",
                source_step_id=questions["step_id"],
                answer="我只做了本地双组检查。结果挑战了原预期，不能推断线上效果。",
            )
        )
        assert any(
            ev.get("public_document_id") == answer["answer_document_id"]
            for ev in answer["result"]["evidence"]
        )
        followup = check(
            run_stage(client, identity, auth, "followup", source_step_id=answer["step_id"])
        )
        check(
            run_stage(
                client,
                identity,
                auth,
                "answer",
                source_step_id=followup["step_id"],
                answer="我没有生产指标；需要控制并发和请求标识才可能区分原因。",
            )
        )
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        results = client.get(base).json()["results"]
        assert len(results) == 4
        assert all(row[key] == record["id"] for row in results)
