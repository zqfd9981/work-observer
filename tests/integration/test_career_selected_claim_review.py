"""An exact claim selection survives editable questions, execution and history reads."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_claim_recheck import LONG_CLAIM, ClaimRecheckModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class SelectedClaimModel(ClaimRecheckModel):
    def __init__(self):
        super().__init__()
        self.selected = []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        continued = context["project_context"]["career_evidence"].get("continued_discussion")
        focus = (continued or {}).get("selected_claim_to_recheck")
        if not focus:
            return await super().turn(history)
        self.selected.append(focus)
        assert focus["claim_index"] == 23 and focus["claim"]["text"] == LONG_CLAIM
        assert "claim.text是旧Agent原句" in focus["notice"]
        assert "第 24 条" not in context["question"]
        assert not context["project_context"]["previous_findings"]
        assert "evidence_ids" not in focus["claim"]
        assert all(
            "id" not in row and "quote" not in row for row in focus["source_references_to_reread"]
        )
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = (
                "read_archived_documents",
                {
                    "reads": [
                        {"document_id": row["public_document_id"], "start": 0}
                        for row in focus["source_references_to_reread"]
                    ],
                },
            )
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "合成查证保留局部条件，生产验收权仍需原文支持。",
                            "evidence_ids": [row["id"] for row in outputs[0]["evidence"]],
                        }
                    ],
                    "gaps": ["局部说明不能证明个人验收权限。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_specific_old_claim_is_frozen_even_when_question_no_longer_names_its_number(tmp_path):
    database = tmp_path / "selected-claim.db"
    upgrade(database)
    model = SelectedClaimModel()
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=tmp_path / "raw"),
            model=model,
            checkpoint_path=tmp_path / "runs.db",
            reports_dir=tmp_path / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save(
            "/api/career",
            {
                "title": "合成点选原判断",
                "goal": "准确核对原句",
                "first_question": "局部样例的边界如何区分？",
                "material_title": "合成原句的依据",
                "material_text": "合成说明：记录局部输入输出，真实验收权限仍未说明。",
            },
        )
        base, qid = "/api/career/" + goal["id"], goal["questions"][0]["id"]
        original = run_stage(
            client, goal["id"], auth, "ask", question_id=qid, question="先按材料建立合成解释。"
        )
        source = original["results"][0]
        assert source["result"]["status"] == "completed"
        assert source["result"]["claims"][23]["text"] == LONG_CLAIM
        saved = deepcopy(source["result"])
        values = {
            "kind": "ask",
            "source_step_id": source["step_id"],
            "claim_review_index": 23,
            "question_id": qid,
            "question": "请核实选定解释的条件与反例。",
        }
        before = client.get(base).json()
        for invalid in [
            {"claim_review_index": 24},
            {"claim_review_index": True},
            {"claim_review_index": -1},
            {"source_step_id": None},
            {"kind": "map"},
        ]:
            rejected = client.post(base + "/prepare", headers=auth, json={**values, **invalid})
            assert rejected.status_code == 422
        assert client.get(base).json() == before
        checked = run_stage(client, goal["id"], auth, **values)
        study = checked["results"][0]
        result = study["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        focus = result["career_learning_context"]["claim_to_review"]
        assert focus["claim_index"] == 23 and focus["source_step_id"] == source["step_id"]
        assert focus["project_id"] == goal["id"] and focus["claim"]["text"] == LONG_CLAIM
        assert study["claim_review_index"] == 23
        assert len(model.selected) == 2 and len(result["evidence"]) == 1
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "runs.db", namespace=str(database.resolve()))
        recalled = LearningNotebook(lambda: project, store).read_research_history(study["step_id"])
        assert recalled["research"]["claim_to_review"] == focus
        note = save(
            base + "/insights",
            {
                "question_id": qid,
                "source_step_id": study["step_id"],
                "previous_view": "原先未区分局部与生产条件。",
                "observation": "按选定原句回读材料。",
                "current_view": "继续保留验收权限未知。",
                "open_question": "还需实际验收材料。",
            },
        )["insights"][-1]
        project = client.get("/api/projects/" + goal["id"]).json()
        memory = LearningNotebook(lambda: project, store).read(note["id"])["note"]
        assert memory["source_claim_review"] == focus
        calls = checked["usage"]["calls"]
        zero = run_stage(
            client, goal["id"], auth, **{**values, "claim_review_index": 0, "offline": True}
        )
        frozen = zero["results"][0]["result"]
        assert frozen["status"] == "evidence_only"
        assert frozen["career_learning_context"]["claim_to_review"]["claim_index"] == 0
        assert (
            frozen["career_learning_context"]["claim_to_review"]["claim"]["text"]
            == saved["claims"][0]["text"]
        )
        assert zero["usage"]["calls"] == calls and len(model.selected) == 2
        old = next(row for row in zero["results"] if row["step_id"] == source["step_id"])
        assert old["result"] == saved
