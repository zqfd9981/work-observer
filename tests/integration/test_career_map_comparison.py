"""Chosen maps remain complete, ordered and available to follow-up research."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class MapComparisonModel(CareerModel):
    def __init__(self):
        super().__init__()
        self.maps = 0

    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] == "finish_research":
            answer = json.loads(call["arguments"])
            if value := answer.get("work_map"):
                self.maps += 1
                label = f"合成地图{self.maps}"
                value["scope_note"] = label + "：只解释当前合成材料，不证明行业变化。"
                value["work_types"] = [{
                    "name": label + "的失败样例验证工作",
                    "problem": "识别重复写入的失败条件，业务效果尚未验证。",
                    "tasks": "构造正常、超时和并发请求。",
                    "deliverables": label + "的样例、日志与观察记录。",
                    "claim_indices": [0, 1], "basis": "inference",
                    "boundary": label + "仅为本地练习，不证明独立上线能力。",
                    "next_check": label + "需要核实实际验收口径。",
                }]
                value["work_relations"][0]["transfer_limit"] = (
                    label + "：" + "仅限合成请求；" * 55 + "末尾限定：未验证生产并发。"
                )
            context = json.loads(history[1]["content"])
            selected = context.get("project_context", {}).get("career_evidence", {}).get(
                "selected_map_comparison"
            )
            if selected:
                answer["claims"][0]["basis"] = "synthesis"
                answer["claims"][0]["text"] = (
                    "两份合成地图的解释范围不同；资料未变，不能据此宣称岗位需求发生变化。"
                )
            call["arguments"] = json.dumps(answer)
        return outputs, call


def test_compare_chosen_maps_across_goal_changes_and_continue(tmp_path):
    database = tmp_path / "map-comparison.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MapComparisonModel()
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
            "title": "合成地图对照岗位", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"]
        goal = {"title": "合成工作理解对照", "goal": "理解任务与交付物",
                "background": "仅有虚构的本地练习。", "job_ids": [job], "constraints": ""}
        identity = post("/api/career", goal)["id"]
        base = f"/api/career/{identity}"
        first = run_stage(client, identity, auth, "map")["results"][0]
        response = client.patch(base, headers=auth, json={**goal, "goal": "核实迁移条件"})
        assert response.status_code == 200, response.text
        second = run_stage(client, identity, auth, "map")["results"][0]
        third = run_stage(client, identity, auth, "map")["results"][0]
        nonmap = run_stage(client, identity, auth, "role")["results"][0]
        other = post("/api/career", {**goal, "title": "另一目标"})["id"]
        foreign = run_stage(client, other, auth, "map")["results"][0]
        for pair in (
            [first["step_id"], first["step_id"]],
            [first["step_id"], nonmap["step_id"]],
            [first["step_id"], foreign["step_id"]],
        ):
            response = client.post(base + "/prepare", headers=auth, json={
                "kind": "ask", "question": "对照地图", "comparison_step_ids": pair,
            })
            assert response.status_code == 422, response.text
        pair = [second["step_id"], first["step_id"]]
        compared = run_stage(client, identity, auth, "ask", question="对照所选地图的迁移边界。",
                             comparison_step_ids=pair)["results"][0]
        assert compared["result"]["status"] == "completed"
        context = model.contexts[-1]["project_context"]["career_evidence"]
        assert context["selected_inquiry"] is None
        selected = context["selected_map_comparison"]
        assert [row["step_id"] for row in selected] == pair
        assert selected[0]["work_map"] == second["result"]["work_map"]
        assert selected[1]["work_map"] == first["result"]["work_map"]
        assert selected[0]["same_job_scope"] and not selected[1]["same_job_scope"]
        assert all(row["source_references_to_reread"] for row in selected)
        assert selected[0]["claim_details_to_recheck"][0]["requirement"] == "required"
        continued = run_stage(client, identity, auth, "ask", question="哪些还不能确定？",
                              source_step_id=compared["step_id"])["results"][0]
        assert continued["comparison_step_ids"] == pair
        assert model.contexts[-1]["project_context"]["career_evidence"][
            "selected_map_comparison"
        ] == selected
        after = client.get(base).json()["results"]
        for old in (first, second, third):
            assert next(row for row in after if row["step_id"] == old["step_id"])["result"][
                "work_map"
            ] == old["result"]["work_map"]
