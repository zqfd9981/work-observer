"""A selected research claim becomes a user-designed test, not an adopted conclusion."""

import json
import re

from starlette.testclient import TestClient
from test_career_claim_recheck import CLAIM_END, LONG_CLAIM, ClaimRecheckModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import (
    LearningNotebook,
    experiment_claim_origin,
    learning_record,
)
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class ClaimExperimentModel(ClaimRecheckModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        personal = context["project_context"]["career_evidence"]
        if not personal.get("selected_experiment_id"):
            return await super().turn(history)
        self.contexts.append(context)
        task = next(
            row
            for row in personal["experiments"]
            if row["id"] == personal["selected_experiment_id"]
        )
        origin = task["claim_to_verify"]
        assert origin["claim_index"] == 23 and origin["claim"]["text"] == LONG_CLAIM
        assert origin["evidence"][0]["start"] == 0
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = (
                "search_experiments",
                {"terms": [CLAIM_END], "offset": 0, "question_id": ""},
            )
        elif len(outputs) == 1:
            assert outputs[-1]["matching_count"] == 1
            name, args = "read_experiments", {"experiment_ids": [task["id"]]}
        elif len(outputs) == 2:
            assert outputs[-1]["experiments"][0]["claim_to_verify"] == origin
            name, args = (
                "read_archived_document",
                {
                    "document_id": origin["evidence"][0]["public_document_id"],
                    "start": 0,
                },
            )
        else:
            evidence = outputs[-1]["evidence"]
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "局部构造记录只能帮助检查条件，"
                            "仍不能证明生产验收权限或个人胜任。",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["实际工作条件与权限仍未知。"],
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


def test_claim_plan_observation_recall_and_learning_keep_the_exact_original(tmp_path):
    database = tmp_path / "claim-experiment.db"
    upgrade(database)
    model = ClaimExperimentModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    app = create_app(settings, model=model, reports_dir=tmp_path / "reports")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save(
            "/api/career",
            {
                "title": "合成判断到实验",
                "goal": "检验研究解释",
                "first_question": "局部样例能解释什么？",
                "material_title": "合成判断原文",
                "material_text": "合成原文🤔\r\n局部输入输出需分别核对，个人验收权限未说明。",
            },
        )
        base, question = "/api/career/" + goal["id"], goal["questions"][0]
        original = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=question["id"],
            question=question["question"],
        )["results"][0]
        assert original["result"]["status"] == "completed"
        before, calls = client.get(base).json(), len(model.contexts)
        plan = {
            "title": "改变输入核对旧解释",
            "task_or_ability": "检验局部条件",
            "deliverable": "预测和实际观察记录",
            "completion_check": "逐项核对差异",
            "hypothesis": "本次要验证的具体解释，尚未执行。",
            "source_step_id": original["step_id"],
            "source_claim_index": 23,
            "question_id": question["id"],
        }
        for invalid in [
            {"source_step_id": None},
            {"source_claim_index": 24},
            {"source_claim_index": True},
            {"source_claim_index": -1},
            {"question_id": None},
            {"source_experiment_id": "0" * 32},
        ]:
            rejected = client.post(base + "/experiments", headers=auth, json={**plan, **invalid})
            assert rejected.status_code == 422, rejected.text
        assert client.get(base).json() == before and len(model.contexts) == calls
        task = save(base + "/experiments", plan)["tasks"][-1]
        assert task["source_claim_index"] == 23 and task["purpose"] == "understanding_check"
        assert task["state"] == "planned" and not task["outcome"] and not task["evidence_ids"]
        updated = save(
            base + "/tasks/" + task["id"],
            {
                "state": "done",
                "outcome": "合成观察：改变一个输入后出现差异，真实工作适用性未知。",
            },
            "patch",
        )
        assert len(model.contexts) == calls
        reflected = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            task_id=task["id"],
            question_id=question["id"],
            question="按观察回查所选原判断。",
        )["results"][0]
        assert reflected["result"]["status"] == "completed", reflected["result"]["stop_reason"]
        read = reflected["result"]["career_learning_context"]["read_experiments"][0]
        assert read["claim_to_verify"]["claim"]["text"] == LONG_CLAIM
        assert read["reported_observation"] == updated["tasks"][0]["outcome"]
        snapshot = client.get(base).json()
        note = save(
            base + "/insights",
            {
                "task_id": task["id"],
                "question_id": question["id"],
                "previous_view": "原解释未被验证。",
                "observation": updated["tasks"][0]["outcome"],
                "current_view": "需要保留输入条件。",
                "open_question": "工作适用性仍未知。",
            },
        )["insights"][-1]
        follow = save(
            base + "/experiments",
            {
                **{
                    key: value
                    for key, value in plan.items()
                    if key not in {"source_step_id", "source_claim_index"}
                },
                "previous_task_id": task["id"],
                "design_change": "再改变一个输入。",
            },
        )["tasks"][-1]
        assert (
            follow["source_step_id"] == original["step_id"] and follow["source_claim_index"] == 23
        )
        assert not follow["outcome"]
        zero = save(base + "/experiments", {**plan, "source_claim_index": 0})["tasks"][-1]
        record = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db", namespace=str(database.resolve()))
        origin = experiment_claim_origin(record, zero, store)
        assert (
            origin["claim_index"] == 0
            and origin["claim"]["text"] == original["result"]["claims"][0]["text"]
        )
        linked = learning_record(note, record, store)["linked_experiment"]
        assert linked["claim_to_verify"] == read["claim_to_verify"]
        notebook = LearningNotebook(lambda: record, store)
        assert (
            notebook.read_experiments([follow["id"]])["experiments"][0]["claim_to_verify"]
            == read["claim_to_verify"]
        )
        final = client.get(base).json()
        assert final["questions"] == before["questions"] and final["results"] == snapshot["results"]
