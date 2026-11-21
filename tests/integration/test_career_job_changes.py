"""A saved change question reads its selected sources even after a newer JD arrives."""

import json
import re
from datetime import datetime

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class JobChangesModel(ModelClient):
    def __init__(self):
        self.last_usage = {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        question = context["project_context"]["career_evidence"]["selected_inquiry"]
        cutoffs = re.findall(r"截止 ([0-9T:.+\-]+)", question["next_evidence"])
        assert len(cutoffs) == 2
        assert len(context["fixed_scope"]["jobs"]) == 1
        job = context["fixed_scope"]["jobs"][0]["id"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if len(outputs) < 2:
            assert "read_historical_job" in {tool["name"] for tool in self.tools}
            name, arguments = "read_historical_job", {
                "job_id": job, "as_of": cutoffs[len(outputs)], "start": 0,
            }
        else:
            assert all(output["status"] == "read" for output in outputs), outputs
            evidence = [output["evidence"][0] for output in outputs]
            name, arguments = "finish_research", {
                "claims": [{
                    "category": "task" if index == 0 else "ability",
                    "basis": "direct", "requirement": "unspecified" if index == 0 else "preferred",
                    "text": item["quote"].split("。")[0] + "。", "evidence_ids": [item["id"]],
                } for index, item in enumerate(evidence)],
                "gaps": ["两份合成手工原文的差异，不能证明企业分工或市场趋势发生变化。"],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(arguments),
                "call_id": str(len(history))}
        return [call], call


def test_change_question_preserves_both_sources_and_cutoffs_when_a_newer_body_arrives(tmp_path):
    database = tmp_path / "job-changes.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, model=JobChangesModel(), reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        def import_body(body):
            return post("/api/import", {
                "title": "合成变化观察岗位", "company": "合成团队", "external_id": "changes-one",
                "description": body, "data_kind": "synthetic",
            })["job_id"]

        job = import_body("负责接口验证。交付本地样例；实际分工未知。")
        assert import_body("商科背景更佳。负责接口验证与业务复盘；实际分工仍未知。") == job
        comparison = client.get("/api/jobs/" + job + "/compare-history").json()
        before, after = comparison["before"], comparison["after"]
        for observation in (before, after):
            assert datetime.fromisoformat(observation["read_as_of"]) == max(
                datetime.fromisoformat(observation[key]) for key in ("observed_at", "processed_at")
            )
        older = next(row for row in comparison["evidence"]
                     if row["snapshot_id"] == before["snapshot_id"])
        later = next(row for row in comparison["evidence"]
                     if row["snapshot_id"] == after["snapshot_id"])
        other = post("/api/import", {
            "title": "合成无关岗位", "company": "合成团队", "description": "不参与本次变化观察。",
            "data_kind": "synthetic",
        })["job_id"]
        identity = post("/api/career", {
            "title": "合成：分清来源与认识变化", "goal": "核对两次保存的JD含义",
            "job_ids": [job, other],
        })["id"]
        base = "/api/career/" + identity

        def passage(row):
            return {key: row[key] for key in ("document_id", "snapshot_id", "start", "end")}

        question = post(base + "/questions", {
            "question": "任务与要求真的变了吗，还是表述或我们的理解变了？",
            "selected_job_ids": [job], "source_passage": passage(older),
            "next_evidence": (
                f"按来源截止 {before['read_as_of']} 与截止 {after['read_as_of']} 回读。"
            ),
            "hypothesis_a": "可能是任务变化", "hypothesis_b": "也可能是表述变化",
        })["questions"][0]
        post(base + "/questions/" + question["id"] + "/passages", {
            "passage": passage(later), "user_note": "较晚取得的对照，含义待核实。",
        })
        assert import_body("后来第三份正文只写运维，不能替换已选的前两份。") == job
        latest = client.get("/api/jobs/" + job + "/compare-history").json()["after"]["snapshot_id"]
        studied = run_stage(client, identity, auth, "ask", question=question["question"],
                            question_id=question["id"])
        result = studied["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == 3
        assert {item["snapshot_id"] for item in result["evidence"]} == {
            before["snapshot_id"], after["snapshot_id"],
        }
        assert latest not in {item["snapshot_id"] for item in result["evidence"]}
        assert result["claims"][1]["requirement"] == "preferred"
        saved = studied["questions"][0]
        assert saved["source_passage"]["quote"] == older["quote"]
        assert saved["evidence_passages"][0]["quote"] == later["quote"]
        assert saved["state"] == "open" and len(studied["jobs"]) == 2
