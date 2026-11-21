"""An experiment can become a personal revision and an evidence-scoped next inquiry."""

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

UNDERSTANDING = (
    "合成实验认识：" + "总体变化不能替代各分群核对。🤔" * 55 + "末尾：不能外推真实产品。"
)
UNKNOWN = "在相同指标与人群口径下，哪些实际观察能区分体验改善与人群构成变化？"


class ExperimentUnderstandingModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        note = inquiry["origin_learning_note"]
        assert note["current_user_view"] == UNDERSTANDING
        assert note["open_question"] == UNKNOWN and not note["use_for_research"]
        task = note["linked_experiment"]
        assert task["hypothesis"] == "总体更高，就表示每个人群都变好？"
        assert "320/400" in task["comparison_rows"][0]["input"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "read_archived_document", {
                "document_id": task["artifact_document_id"], "start": 0,
            }
        else:
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference", "requirement": "unspecified",
                            "text": "合成计算记录给出总体与分群对照；仍不能据此证明真实业务因果。",
                            "evidence_ids": [outputs[0]["evidence"][0]["id"]]}],
                "gaps": ["仍需核对真实指标口径与样本来源。"],
            }
            if context["project_context"].get("previous_findings"):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_experiment_revision_becomes_a_persistent_inquiry_without_automatic_adoption(tmp_path):
    database = tmp_path / "experiment-understanding.db"
    upgrade(database)
    model = ExperimentUnderstandingModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成实验到认识", "goal": "沿着反例继续调查",
            "first_question": "总体指标上涨代表什么？", "material_title": "合成指标工作说明",
            "material_text": "核对指标口径和人群构成；计算不能单独证明真实业务改进。",
        })
        base, parent = "/api/career/" + goal["id"], goal["focus_question_id"]
        saved = post(base + "/experiments/cohorts", {
            **INPUT, "question_id": parent, "hypothesis": "总体更高，就表示每个人群都变好？",
            "save": True,
        })
        task = saved["career"]["tasks"][0]
        old = post(base + "/insights", {
            "previous_view": "原先没考虑分群", "observation": "读到效果指标要求",
            "current_view": "总体更高，就表示每个人群都变好？", "question_id": parent,
        })["insights"][-1]
        notes = post(base + "/insights", {
            "task_id": task["id"], "question_id": parent, "replaces_insight_id": old["id"],
            "previous_view": old["current_view"], "observation": task["outcome"],
            "current_view": UNDERSTANDING, "open_question": UNKNOWN,
        })
        note = notes["insights"][-1]
        assert not notes["insights"][0]["use_for_research"] and not notes["results"]
        post(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        before = deepcopy(client.get(base).json())
        bad = client.post(base + "/questions", headers=auth, json={
            "question": UNKNOWN, "source_insight_id": "0" * 32,
        })
        assert bad.status_code == 422 and client.get(base).json() == before
        after = post(base + "/questions", {
            "question": UNKNOWN, "source_insight_id": note["id"], "parent_question_id": parent,
            "material_ids": [task["artifact_document_id"]],
        })
        followup = after["questions"][-1]
        assert followup["state"] == "open" and followup["conclusion"] == ""
        assert after["questions"][0] == before["questions"][0]
        assert after["insights"] == before["insights"] and after["tasks"] == before["tasks"]
        assert not model.contexts and not after["results"]
        study = run_stage(client, goal["id"], auth, "ask", question_id=followup["id"],
                          question="合成实验认识：沿着保留的未知回读产物，核对解释的边界。")
        result = study["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        origin = result["career_learning_context"]["origin_learning_note"]
        assert origin["current_user_view"] == UNDERSTANDING
        assert origin["linked_experiment"] == task
        assert not origin["use_for_research"]
        assert {row["public_document_id"] for row in result["evidence"]} == {
            task["artifact_document_id"],
        }
        final = client.get(base).json()
        assert final["insights"] == after["insights"] and final["tasks"] == after["tasks"]
        assert final["questions"] == after["questions"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = client.get(base).json()
        assert restored["questions"][-1]["source_insight_id"] == note["id"]
        assert restored["results"][0]["result"]["career_learning_context"][
            "origin_learning_note"
        ] == origin
