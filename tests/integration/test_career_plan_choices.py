"""People can choose one suggested experiment without adopting the entire plan."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class ChoiceModel(CareerModel):
    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] == "finish_research":
            arguments = json.loads(call["arguments"])
            if plan := arguments.get("application_plan"):
                original = plan["actions"][0]
                plan["actions"] = [
                    {**original, "title": title, "hypothesis": hypothesis}
                    for title, hypothesis in (
                        ("合成方案一：正常响应组", "正常响应可能不重复，仍待验证。"),
                        ("合成方案二：超时响应组", "超时可能触发重复，仍待验证。"),
                        ("合成方案三：并发请求组", "并发可能触发重复，仍待验证。"),
                    )
                ]
                call["arguments"] = json.dumps(arguments)
        return outputs, call


def test_choose_one_then_adapt_and_add_remaining_without_overwriting(tmp_path):
    database = tmp_path / "choices.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ChoiceModel()
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        job = post("/api/import", {
            "title": "合成方案选择岗位", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"]
        identity = post("/api/career", {
            "title": "合成：先选择一项验证", "goal": "根据投入安排实验",
            "background": "只有本地合成练习。", "job_ids": [job],
        })["id"]
        base = f"/api/career/{identity}"
        planned = run_stage(client, identity, auth, "plan")["results"][0]
        original_plan = planned["result"]["application_plan"]
        assert len(original_plan["actions"]) == 3
        payload = {"step_id": planned["step_id"]}
        calls = len(model.contexts)
        for indices in ([], [3], [-1], [True]):
            response = client.post(base + "/tasks", headers=auth, json={
                **payload, "action_indices": indices,
            })
            assert response.status_code == 422, response.text
            assert not client.get(base).json()["tasks"]
        selected = post(base + "/tasks", {**payload, "action_indices": [1]})["tasks"]
        assert len(selected) == 1
        task = selected[0]
        assert task["title"] == original_plan["actions"][1]["title"]
        assert task["hypothesis"] == original_plan["actions"][1]["hypothesis"]
        assert task["source_key"] == planned["run_id"] + ":1"
        assert post(base + "/tasks", {**payload, "action_indices": [1, 1]})["tasks"] == selected
        response = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "doing", "title": "按我的时间缩小为两个失败样例", "outcome": "",
            "deliverable": "仅保留两个样例和观察，不声称完成全量验证。",
        })
        assert response.status_code == 200, response.text
        edited = response.json()["tasks"][0]
        all_tasks = post(base + "/tasks", payload)["tasks"]
        assert len(all_tasks) == 3 and all_tasks[0] == edited
        assert [row["source_key"] for row in all_tasks] == [
            planned["run_id"] + ":" + str(index) for index in (1, 0, 2)
        ]
        assert post(base + "/tasks", payload)["tasks"] == all_tasks
        result = client.get(base).json()["results"][0]
        assert result["result"]["application_plan"] == original_plan
        assert len(model.contexts) == calls
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        assert client.get(base).json()["tasks"] == all_tasks
