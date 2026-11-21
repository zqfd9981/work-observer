"""Revisit a saved question using both the original and current JD sources."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import CareerModel, run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class SourceReviewModel(CareerModel, ModelClient):
    def __init__(self):
        super().__init__()
        self.review, self.last_usage = True, {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        personal = context["project_context"].get("career_evidence", {})
        if not self.review or context["project_context"].get("career_action") != "ask":
            return await super().turn(history)
        self.contexts.append(context)
        inquiry = personal["selected_inquiry"]
        source = next(iter(inquiry["earlier_discussions"]), None) or inquiry["origin_discussion"]
        assert source["source_cutoff"]
        original = next(row for row in source["source_references_to_reread"] if row["job_id"])
        assert original["snapshot_id"] and original["document_id"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, arguments = "read_job", {"job_id": original["job_id"], "start": 0}
        elif len(outputs) == 1:
            name, arguments = "read_historical_job", {
                "job_id": original["job_id"], "as_of": source["source_cutoff"], "start": 0,
            }
        else:
            current, previous = outputs[0]["evidence"][0], outputs[1]["evidence"][0]
            assert previous["snapshot_id"] == original["snapshot_id"]
            assert current["snapshot_id"] != previous["snapshot_id"]
            name, arguments = "finish_research", {
                "claims": [{
                    "category": "task", "basis": "synthesis", "requirement": "unspecified",
                    "text": "合成前后原文已有差异，变化的工作含义仍待实际分工与条件核实。",
                    "evidence_ids": [current["id"], previous["id"]],
                }],
                "gaps": ["人工保存的原文变化，不能单独证明企业实际调整或行业趋势。"],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(arguments),
                "call_id": str(len(history))}
        return [call], call


def test_source_followup_rereads_original_and_current_without_rewriting_user_conclusion(tmp_path):
    database = tmp_path / "source-followup.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = SourceReviewModel()
    model.review = False
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        old_text = "必须掌握Python接口开发与测试。负责失败样例验证。"
        job = post("/api/import", {
            "title": "合成来源复查岗位", "company": "合成团队", "description": old_text,
            "data_kind": "synthetic",
        })["job_id"]
        identity = post("/api/career", {
            "title": "合成：新资料与原判断", "goal": "重查变化是否影响工作解释", "job_ids": [job],
        })["id"]
        base = "/api/career/" + identity
        origin = run_stage(client, identity, auth, "role")["results"][0]
        conclusion = "当时只核对本地接口验证，业务分工和迁移条件未知。"
        question = post(base + "/questions", {
            "question": "岗位实际要验证什么，哪些责任仍未知？", "state": "answered",
            "conclusion": conclusion, "source_step_id": origin["step_id"],
            "conclusion_step_id": origin["step_id"], "selected_job_ids": [job],
        })["questions"][0]
        first = run_stage(client, identity, auth, "ask", question=question["question"],
                          question_id=question["id"])["results"][0]
        post(base + "/jobs/" + job + "/observations", {
            "description": "必须掌握Python接口开发与测试。负责失败验证与业务复盘。",
            "data_kind": "synthetic",
        })
        changed = client.get(base).json()
        old = next(row for row in changed["results"] if row["step_id"] == first["step_id"])
        issues = old["result"]["audit"]["changed_sources"]
        assert issues[0]["reason"] == "job_current_version_changed"
        model.review = True
        checked = run_stage(client, identity, auth, "ask", question_id=question["id"],
                            question="请读取当前JD，再对照原来阅读的原文与判断。")
        current = checked["results"][0]
        result = current["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == 3 and not result["audit"]["changed_sources"]
        assert result["trace"][1]["tool"] == "read_historical_job"
        assert any(item["quote"] == old_text for item in result["evidence"])
        assert any("业务复盘" in item["quote"] for item in result["evidence"])
        context = model.contexts[-1]["project_context"]["career_evidence"]["selected_inquiry"]
        assert context["origin_discussion"]["source_cutoff"] == origin["result"]["created_at"]
        assert context["earlier_discussions"][0]["source_cutoff"] == first["result"]["created_at"]
        assert checked["questions"][0] == question
        retained = next(row for row in checked["results"] if row["step_id"] == first["step_id"])
        assert retained["result"]["evidence"] == first["result"]["evidence"]
        assert retained["result"]["claims"] == first["result"]["claims"]
