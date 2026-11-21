"""A question keeps its originating explanation through experiment and reflection."""

import json
import re

from starlette.testclient import TestClient
from test_career_map_comparison import MapComparisonModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.storage.database import upgrade


class MapInquiryModel(MapComparisonModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        source = next((row for row in context["fixed_scope"].get("public_document_titles", [])
                       if row["title"].startswith("合成关系起点资料")), None)
        if source and outputs and not any(
            ev.get("public_document_id") == source["id"]
            for output in outputs for ev in output.get("evidence", [])
        ):
            self.contexts.append(context)
            call = {"type": "function_call", "name": "read_archived_document",
                    "arguments": json.dumps({"document_id": source["id"], "start": 0}),
                    "call_id": str(len(history))}
            return [call], call
        returned, call = await super().turn(history)
        if call["name"] == "finish_research":
            answer = json.loads(call["arguments"])
            if plan := answer.get("application_plan"):
                plan["actions"][0]["hypothesis"] = (
                    "原地图把失败验证与接口测试能力联系起来；先检验合成请求条件，生产迁移仍未知。"
                )
            call["arguments"] = json.dumps(answer)
        return returned, call


def test_question_origin_remains_complete_and_its_available_sources_stay_readable(tmp_path):
    database = tmp_path / "map-inquiry.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MapInquiryModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        job = post("/api/import", {
            "title": "合成关系调查岗位", "company": "合成团队", "data_kind": "synthetic",
            "description": "必须掌握Python接口开发与测试。负责失败样例验证。",
        })["job_id"]
        identity = post("/api/career", {
            "title": "合成：从地图关系到实验", "goal": "核实工作关系的迁移条件",
            "background": "本地虚构练习。", "job_ids": [job],
        })["id"]
        base = f"/api/career/{identity}"
        source = post(base + "/materials", {
            "title": "合成关系起点资料", "text": "合成说明：仅描述本地失败样例；生产并发未验证。",
        })["materials"][0]
        origin = run_stage(client, identity, auth, "map")["results"][0]
        assert any(ev.get("public_document_id") == source["id"]
                   for ev in origin["result"]["evidence"])
        calls = len(model.contexts)
        question = post(base + "/questions", {
            "question": "请查证问题起点的工作地图中，第 1 条工作关系。",
            "source_step_id": origin["step_id"],
        })["questions"][0]
        assert len(model.contexts) == calls
        for n in range(22):
            post(base + "/materials", {"title": f"无关合成记录{n}", "text": "无关的合成说明。"})
        planned = run_stage(client, identity, auth, "plan", question_id=question["id"])
        row = planned["results"][0]
        assert row["result"]["status"] == "completed"
        inquiry = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        reference = inquiry["origin_discussion"]
        assert reference["step_id"] == origin["step_id"]
        assert reference["work_map"] == origin["result"]["work_map"]
        assert reference["claim_details_to_recheck"][0]["requirement"] == "required"
        assert source["id"] in row["document_ids"] and row["omitted_documents"]
        assert any(ev.get("public_document_id") == source["id"]
                   for ev in row["result"]["evidence"])
        task = post(base + "/tasks", {"step_id": row["step_id"], "action_indices": [0]})["tasks"][0]
        assert task["question_id"] == question["id"] and "生产迁移仍未知" in task["hypothesis"]
        response = client.patch(base + "/tasks/" + task["id"], headers=auth, json={
            "state": "done", "outcome": "两组都重复写入，尚不能说明原因。",
            "artifact_text": "合成记录：normal=2, timeout=2；未核对并发。",
        })
        assert response.status_code == 200, response.text
        reflected = run_stage(client, identity, auth, "reflect", task_id=task["id"])
        assert reflected["results"][0]["result"]["status"] == "completed"
        personal = model.contexts[-1]["project_context"]["career_evidence"]
        assert personal["selected_inquiry"]["origin_discussion"] == reference
        assert personal["experiments"][0]["reported_observation"] == (
            "两组都重复写入，尚不能说明原因。"
        )
        assert client.get(base).json()["questions"][0]["state"] == "open"
        removed = client.delete(base + "/materials/" + source["id"], headers=auth)
        assert removed.status_code == 200, removed.text
        after = run_stage(client, identity, auth, "plan", question_id=question["id"])
        assert source["id"] not in after["document_ids"]
        assert source["id"] not in after["results"][0]["document_ids"]
        assert not any(ev.get("public_document_id") == source["id"]
                       for ev in after["results"][0]["result"]["evidence"])
        assert model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"][
            "origin_discussion"
        ] == reference
