"""A local model substitute runs cohort arithmetic, then rereads the work source."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_cohort_experiment import INPUT
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

HYPOTHESIS = "合成预期：总体转化率上涨，是否就代表每个人群都改善？"


class CohortProbeModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        assert "run_cohort_comparison" in {row["name"] for row in self.tools}
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "run_cohort_comparison", {**INPUT, "hypothesis": HYPOTHESIS}
        elif len(outputs) == 1:
            output = outputs[0]
            assert output["overall"]["composition_reversal"]
            assert output["overall"]["after_with_before_mix"] == .2
            assert output["data_kind"] == "synthetic" and "evidence" not in output
            assert output["hypothesis"] == HYPOTHESIS
            source = next(row["id"] for row in context["fixed_scope"]["public_document_titles"]
                          if row["title"].startswith("合成分群原文"))
            name, args = "read_archived_document", {"document_id": source, "start": 0}
        else:
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference", "requirement": "unspecified",
                            "text": "合成原文要求核对口径与人群构成。构造计数中A总体26%、"
                                    "B总体65%，按A占比重算B为20%；这不能证明真实产品改进。",
                            "evidence_ids": [row["id"] for row in outputs[-1]["evidence"]]}],
                "gaps": ["真实数据口径、人群定义、样本来源与业务结果仍需核实。"],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_agent_cohort_probe_keeps_inputs_separate_from_evidence_and_tasks(tmp_path):
    database = tmp_path / "agent-cohort.db"
    upgrade(database)
    model = CohortProbeModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        response = client.post("/api/career", headers=auth, json={
            "title": "合成Agent分群计算", "goal": "检验总体与分群的解释边界",
            "first_question": "总体指标上涨，是否足以说明产品更好？",
            "material_title": "合成分群原文",
            "material_text": "产品原型验证应记录效果，核对指标口径与样本构成。"
                             "分群比率和总体比率需分别对照，计算不能单独证明因果或真实业务改进。",
        })
        assert response.status_code == 201, response.text
        goal = response.json()
        identity, qid, raw = goal["id"], goal["focus_question_id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        before = deepcopy(client.get(base).json())
        study = run_stage(client, identity, auth, "ask", question_id=qid,
                          question="合成分群判断：先构造能区分总体与人群解释的输入，再回读原文。")
        result = study["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == 3
        probe = result["career_learning_context"]["cohort_experiments"][0]
        assert probe["hypothesis"] == HYPOTHESIS
        assert probe["overall"]["after_with_before_mix"] == .2
        assert [row["name"] for row in probe["groups"]] == [row["name"] for row in INPUT["groups"]]
        assert [row["tool"] for row in result["trace"]][:2] == [
            "run_cohort_comparison", "read_archived_document",
        ]
        assert {row["public_document_id"] for row in result["evidence"]} == {raw}
        after = client.get(base).json()
        assert after["questions"] == before["questions"]
        assert after["materials"] == before["materials"]
        assert not after["tasks"] and not after["insights"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = client.get(base).json()["results"][0]["result"]
        assert restored["career_learning_context"]["cohort_experiments"] == [probe]
