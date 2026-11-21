"""Generated experiments retain their proposed explanation through observation and revision."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.reports.results import render
from work_observer.storage.database import upgrade

FIRST = "若重复写入只由超时重试触发，则正常响应组不应重复写入；这仍是待检验解释。"
NEXT = "若重复写入只由并发竞争触发，则关闭并发后不应继续重复写入；仍待验证。"


class HypothesisModel(CareerModel):
    """Local responses carry proposed explanations, not an assertion that they are true."""

    async def turn(self, history):
        outputs, call = await super().turn(history)
        context = json.loads(history[1]["content"])
        if (
            call["name"] == "finish_research"
            and context["project_context"]["career_action"] == "plan"
        ):
            arguments = json.loads(call["arguments"])
            action = arguments["application_plan"]["actions"][0]
            continuing = context["project_context"]["career_evidence"]["selected_experiment_id"]
            action["hypothesis"] = NEXT if continuing else FIRST
            action["completion_check"] = (
                "固定请求标识，比较单线程与并发；若单线程也重复写入，就挑战只由并发触发的解释。"
                if continuing
                else "比较正常与超时响应；若正常组也重复写入，就挑战只由重试触发的解释。"
            )
            call["arguments"] = json.dumps(arguments)
        return outputs, call


def test_generated_expectations_survive_progress_updates_and_inform_the_next_experiment(tmp_path):
    database = tmp_path / "hypotheses.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = HypothesisModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        job = client.post(
            "/api/import",
            headers=auth,
            json={
                "title": "合成可检验实验岗位",
                "company": "合成团队",
                "data_kind": "synthetic",
                "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
            },
        ).json()["job_id"]
        identity = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成解释与反例闭环",
                "goal": "对照原先解释与实际观察",
                "background": "只有本地虚构练习。",
                "job_ids": [job],
            },
        ).json()["id"]
        base = f"/api/career/{identity}"
        planned = run_stage(client, identity, auth, "plan")["results"][0]
        assert planned["result"]["application_plan"]["actions"][0]["hypothesis"] == FIRST
        assert FIRST in render(planned["result"])
        task = client.post(
            base + "/tasks", headers=auth, json={"step_id": planned["step_id"]}
        ).json()["tasks"][0]
        assert task["hypothesis"] == FIRST and not task["outcome"]
        calls = len(model.contexts)
        observed = "合成观察：正常组和超时组都重复写入，尚未控制并发；原解释受到挑战。"
        recorded = client.patch(
            base + "/tasks/" + task["id"],
            headers=auth,
            json={
                "state": "done",
                "outcome": observed,
                "artifact_text": "合成日志：normal writes=2；timeout writes=2；未控制并发。",
            },
        )
        assert recorded.status_code == 200, recorded.text
        original_task = recorded.json()["tasks"][0]
        assert original_task["hypothesis"] == FIRST
        assert len(model.contexts) == calls
        run_stage(client, identity, auth, "reflect", task_id=task["id"])
        context = model.contexts[-1]["project_context"]["career_evidence"]["experiments"][0]
        assert context["prior_expectation"] == FIRST and context["reported_observation"] == observed
        next_plan = run_stage(client, identity, auth, "plan", task_id=task["id"])["results"][0]
        assert next_plan["result"]["application_plan"]["actions"][0]["hypothesis"] == NEXT
        imported = client.post(
            base + "/tasks", headers=auth, json={"step_id": next_plan["step_id"]}
        ).json()
        child = imported["tasks"][-1]
        assert child["hypothesis"] == NEXT and child["previous_task_id"] == task["id"]
        assert not child["outcome"] and child["state"] == "planned"
        assert imported["tasks"][0] == original_task
        again = client.post(
            base + "/tasks", headers=auth, json={"step_id": planned["step_id"]}
        ).json()
        assert again["tasks"] == imported["tasks"]
        assert (
            next(row for row in again["results"] if row["step_id"] == planned["step_id"])["result"][
                "application_plan"
            ]["actions"][0]["hypothesis"]
            == FIRST
        )
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        tasks = client.get(base).json()["tasks"]
        assert tasks[0]["hypothesis"] == FIRST and tasks[1]["hypothesis"] == NEXT
