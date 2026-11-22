import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade

INPUT = {
    "cases": [
        {"name": "应处理工单", "score": 0.55, "needs_action": True},
        *[
            {"name": f"普通工单{i}", "score": score, "needs_action": False}
            for i, score in enumerate(
                [0.6, 0.52, 0.4, 0.35, 0.25, 0.2, 0.15, 0.1, 0.05, 0.03, 0.01]
            )
        ],
    ],
    "thresholds": [0.5, 0.7],
    "signal": "需要进一步处理的工单",
    "conditions": "构造案例，参照标签和分数固定；仅改变筛选阈值。",
    "data_kind": "synthetic",
    "false_positive_cost": 1,
    "false_negative_cost": 20,
    "review_cost": 0,
}
HYPOTHESIS = "合成预期：提高正确率，是否也会降低给定的漏报代价？"


class ThresholdModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        assert "run_threshold_comparison" in {row["name"] for row in self.tools}
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            inputs = INPUT
            remembered = context["project_context"]["career_evidence"].get("selected_learning_note")
            if remembered:
                calculation = remembered["source_calculations"]["threshold_experiments"][0]
                assert calculation["false_negative_cost"] == 20
                assert "不表示本轮已经重新执行" in remembered["source_calculation_notice"]
                inputs = {key: calculation[key] for key in INPUT}
            name, args = "run_threshold_comparison", {**inputs, "hypothesis": HYPOTHESIS}
        elif len(outputs) == 1:
            result = outputs[0]
            low, high = result["policies"]
            assert high["accuracy"] > low["accuracy"]
            assert [low["total_cost"], high["total_cost"]] == [2, 20]
            assert result["data_kind"] == "synthetic" and "evidence" not in result
            assert result["hypothesis"] == HYPOTHESIS and high["precision"] is None
            source = next(
                row["id"]
                for row in context["fixed_scope"]["public_document_titles"]
                if row["title"] == "合成工单原文"
            )
            name, args = "read_archived_document", {"document_id": source, "start": 0}
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "合成原文要求核对工单筛选条件。构造案例中，"
                            "提高阈值后的正确率更高，"
                            "给定总代价却由2增至20；仍需核对实际漏报代价与标签来源。",
                            "evidence_ids": [row["id"] for row in outputs[-1]["evidence"]],
                        }
                    ],
                    "gaps": ["真实案例分布、标签正确性和实际处理约束仍需核实。"],
                },
            )
        if name == "finish_research" and (
            context["project_context"].get("previous_findings")
            or context["project_context"].get("historical_reply")
        ):
            args["revisions"] = []
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_local_counterexample_can_be_saved_and_reopened_without_a_model_call(tmp_path):
    database = tmp_path / "threshold.db"
    upgrade(database)
    model = ThresholdModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    kwargs = {"model": model, "reports_dir": tmp_path / "reports"}
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(
                r'name="wo-token" content="([^"]+)"',
                client.get("/").text,
            )[1]
        }
        goal = client.post(
            "/api/career",
            headers=auth,
            json={
                "title": "合成筛选取舍",
                "goal": "理解误报、漏报与处理代价",
                "first_question": "正确率更高的筛选方案，是否一定更合适？",
                "material_title": "合成工单原文",
                "material_text": "工单筛选应比较误报、漏报和处理工作量。",
            },
        ).json()
        base = "/api/career/" + goal["id"]
        endpoint = base + "/experiments/thresholds"
        values = {**INPUT, "hypothesis": HYPOTHESIS, "question_id": goal["focus_question_id"]}
        response = client.post(endpoint, headers=auth, json=values)
        assert response.status_code == 200, response.text
        calculated = response.json()["experiment"]
        assert calculated["policies"][1]["total_cost"] == 20
        assert client.get(base).json() == goal and not model.contexts
        saved = client.post(endpoint, headers=auth, json={**values, "save": True})
        assert saved.status_code == 201, saved.text
        result = saved.json()
        task = result["career"]["tasks"][-1]
        assert task["id"] == result["task_id"] and task["state"] == "done"
        assert task["hypothesis"] == HYPOTHESIS and task["question_id"] == goal["focus_question_id"]
        assert task["comparison_rows"] == calculated["comparison_rows"] and not model.contexts
        raw = client.get("/api/public-documents/" + task["artifact_document_id"]).json()
        assert calculated["artifact_text"] in raw["text"]
        assert "构造的虚构案例与参照标签" in raw["text"] and HYPOTHESIS in raw["text"]
        assert raw["evidence_kind"] == "work_material"
        bad = client.post(
            endpoint, headers=auth, json={**values, "thresholds": [0.5, 0.5], "save": True}
        )
        assert bad.status_code == 422 and len(client.get(base).json()["tasks"]) == 1
        before = deepcopy(client.get(base).json())
        researched = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=goal["focus_question_id"],
            question="合成阈值取舍：构造案例后，回读原文核对条件。",
        )
        observed = researched["results"][0]["result"]
        assert observed["status"] == "completed", observed.get("stop_reason")
        assert observed["model_calls"] == 3
        probe = observed["career_learning_context"]["threshold_experiments"][0]
        assert probe["cases"] == INPUT["cases"] and probe["hypothesis"] == HYPOTHESIS
        assert [row["tool"] for row in observed["trace"]][:2] == [
            "run_threshold_comparison",
            "read_archived_document",
        ]
        assert {row["public_document_id"] for row in observed["evidence"]} == {
            goal["materials"][0]["id"],
        }
        assert (
            researched["tasks"] == before["tasks"] and researched["insights"] == before["insights"]
        )
        source_step = researched["results"][0]["step_id"]
        noted = client.post(
            base + "/insights",
            headers=auth,
            json={
                "source_step_id": source_step,
                "source_claim_index": None,
                "question_id": goal["focus_question_id"],
                "previous_view": "合成旧理解：只看整体正确率。",
                "observation": "给定的漏报代价改变了这组案例的取舍。",
                "current_view": "合成新理解：先明确错误类型与业务条件。",
                "open_question": "真实标签与代价仍需核实。",
            },
        )
        assert noted.status_code == 201, noted.text
        note = noted.json()["insights"][-1]
        record = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db", namespace=str(database.resolve()))
        notebook = LearningNotebook(lambda: record, store)
        old = notebook.read_research_history(source_step)["research"]
        assert old["local_calculations"] == {"threshold_experiments": [probe]}
        assert (
            notebook.search_research_history(["普通工单10"])["research"][0]["calculation_count"]
            == 1
        )
        assert notebook.search(["普通工单10"])["notes"][0]["id"] == note["id"]
        recalled = notebook.read(note["id"])["note"]
        assert recalled["source_calculations"] == old["local_calculations"]
        found = client.get("/api/career/search", params={"q": "普通工单10"}).json()
        assert {source_step, note["id"]} <= {row["id"] for row in found["records"]}
        recalled["source_calculations"]["threshold_experiments"][0]["cases"][-1]["name"] = "changed"
        assert notebook.read(note["id"])["note"]["source_calculations"] == old["local_calculations"]
        other = LearningNotebook(lambda: {"id": "other"}, store, project_lister=lambda: [record])
        assert {
            row["kind"] for row in other.search_other_goal_memory(["普通工单10"])["memories"]
        } == {"insight", "research"}
        revisited = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=goal["focus_question_id"],
            insight_id=note["id"],
            question="从保存认识的原计算条件重新核对。",
        )
        assert revisited["results"][0]["result"]["status"] == "completed"
        assert (
            model.contexts[-1]["project_context"]["career_evidence"]["selected_learning_note"][
                "source_calculations"
            ]
            == old["local_calculations"]
        )
    with TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1") as client:
        assert client.get(base).json()["results"][0]["result"]["career_learning_context"][
            "threshold_experiments"
        ] == [probe]
