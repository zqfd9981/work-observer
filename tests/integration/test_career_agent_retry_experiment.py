"""The research agent can run a bounded local probe without treating it as source evidence."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

PREDICTION = ("请求编号与业务动作的区分需要通过输入比较。" * 50
              + "末尾预期限定：不推断实际业务协议。")


class RetryProbeModel(ModelClient):
    """Local scripted decisions; the real tool computes the resulting observations."""

    def __init__(self):
        self.bad_first = self.cite_probe = False
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        assert "run_retry_experiment" in {row["name"] for row in self.tools}
        assert "不是从JD独立核实的业务协议" in history[0]["content"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        local = next((row for row in outputs
                      if row.get("kind") == "local_sequential_simulation"), None)
        raw = next((row for row in outputs if row.get("evidence")), None)
        cases = [
            {"name": "重试更换编号", "requests": [
                {"request_id": "r1", "business_id": "业务A", "action": "确认"},
                {"request_id": "r2", "business_id": "业务A", "action": "确认"},
            ]},
            {"name": "同一业务两种动作", "requests": [
                {"request_id": "r1", "business_id": "业务A", "action": "确认"},
                {"request_id": "r2", "business_id": "业务A", "action": "取消<局部模拟条件>"},
            ]},
        ]
        if not local:
            name, args = "run_retry_experiment", {"hypothesis": PREDICTION, "cases": cases}
            if self.bad_first and not outputs:
                args["save"] = True
            elif self.bad_first:
                assert outputs[-1]["error"] == "INVALID_RETRY_EXPERIMENT_INPUT"
        elif not raw:
            assert local["hypothesis"] == PREDICTION
            assert local["cases"][0]["runs"][1]["accepted"] == [1, 2]
            assert local["cases"][1]["runs"][2]["skipped"] == [2]
            assert local["cases"][1]["runs"][3]["accepted"] == [1, 2]
            assert "evidence_ids" not in json.dumps(local) and "artifact_text" not in local
            source = next(row for row in context["fixed_scope"]["public_document_titles"]
                          if row["title"].startswith("合成Agent模拟原文"))
            name, args = "read_archived_document", {"document_id": source["id"], "start": 0}
        else:
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "inference",
                            "requirement": "unspecified",
                            "text": "合成工作资料只说明核对失败与重复记录，"
                            "实际业务键与并发条件仍未知。",
                            "evidence_ids": ["local_sequential_simulation"] if self.cite_probe
                            else [row["id"] for row in raw["evidence"]]}],
                "gaps": ["本地模拟不覆盖真实服务，并发与恢复仍未知。"],
            }
            if context["project_context"].get("previous_findings") or context[
                "project_context"
            ].get("historical_reply"):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("bad_first", [False, True])
def test_agent_runs_and_keeps_full_local_observation_separate_from_originals(tmp_path, bad_first):
    database = tmp_path / "agent-retry.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = RetryProbeModel()
    model.bad_first = bad_first
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        response = client.post("/api/career", headers=auth, json={
            "title": "合成Agent自动实验", "goal": "用反例理解规则，回到原文核对边界",
            "first_question": "重试与业务操作的边界是什么？",
            "material_title": "合成Agent模拟原文",
            "material_text": "合成工作说明：核对失败与重复记录，交付样例和观察。"
            "实际业务键、并发与恢复未说明。",
        })
        assert response.status_code == 201, response.text
        before = response.json()
        data = run_stage(
            client, before["id"], auth, "ask", question="合成Agent自动实验：比较输入再回查原文。",
            question_id=before["focus_question_id"],
        )
        row = data["results"][0]
        result = row["result"]
        assert result["status"] == "completed", result
        probes = result["career_learning_context"]["local_experiments"]
        assert len(probes) == 1 and probes[0]["hypothesis"] == PREDICTION
        assert probes[0]["cases"][1]["requests"][1]["action"] == "取消<局部模拟条件>"
        trace = [entry for entry in result["trace"] if entry["tool"] == "run_retry_experiment"]
        assert trace[-1]["case_count"] == 2 and trace[-1]["request_count"] == 4
        if bad_first:
            assert trace[0]["validation"] == "INVALID_RETRY_EXPERIMENT_INPUT"
        assert data["tasks"] == before["tasks"] == []
        assert data["insights"] == before["insights"] == []
        assert data["questions"] == before["questions"]
        assert data["document_ids"] == before["document_ids"]
        assert all(ev["public_document_id"] == before["materials"][0]["id"]
                   for ev in result["evidence"])
        assert all(key in {ev["id"] for ev in result["evidence"]}
                   for claim in result["claims"] for key in claim["evidence_ids"])
        if not bad_first:
            model.cite_probe = True
            rejected = run_stage(client, before["id"], auth, "ask",
                                 question="合成Agent自动实验：尝试把模拟当原文引用。")
            assert rejected["results"][0]["result"]["status"] != "completed"
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1") as client:
        stored = next(r for r in client.get("/api/career/" + before["id"]).json()["results"]
                      if r["step_id"] == row["step_id"])
        assert stored["result"]["career_learning_context"]["local_experiments"] == probes
