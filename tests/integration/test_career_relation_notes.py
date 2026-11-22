"""A user's interpretation targets one original map edge, without rewriting it."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_work_relations import LIMIT, MATERIALS, RelationsBrowserModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.learning import LearningNotebook
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


class RelationNoteModel(RelationsBrowserModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        selected = context["project_context"]["career_evidence"].get("selected_learning_note")
        if not selected:
            return await super().turn(history)
        self.contexts.append(context)
        origin = selected["source_relation"]
        assert origin["relation_index"] == 0
        assert origin["relation"]["transfer_limit"] == LIMIT + "0"
        assert len(origin["claims"]) == 2 and len(origin["evidence"]) == 1
        assert "历史Agent解释" in selected["source_relation_notice"]
        assert selected["current_user_view"].startswith("合成新理解")
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
                        for row in origin["evidence"]
                    ]
                },
            )
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "responsibility",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "合成资料连接任务与交付物，尚未说明个人验收权限；"
                            "需要进一步核对，不能据产物名称推定个人责任。",
                            "evidence_ids": [row["id"] for row in outputs[0]["evidence"]],
                        }
                    ],
                    "gaps": ["真实验收权限与迁移条件仍需核实。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_relation_zero_keeps_original_limits_and_current_user_notes_separate(tmp_path):
    database = tmp_path / "relation-notes.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = RelationNoteModel()
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(
                r'name="wo-token" content="([^"]+)"',
                client.get("/").text,
            )[1]
        }

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成关系认识", "goal": "核对连接理由与责任边界"})
        base = "/api/career/" + goal["id"]
        ids = [
            save(
                base + "/materials",
                {
                    "title": name,
                    "text": f"任务：{task}。交付：{deliverable}。验收权仍未知。",
                },
            )["materials"][-1]["id"]
            for name, task, deliverable in MATERIALS
        ]
        qid = save(base + "/questions", {"question": "任务怎样产出交付物？", "material_ids": ids})[
            "questions"
        ][-1]["id"]
        mapped = run_stage(
            client,
            goal["id"],
            auth,
            "map",
            question_id=qid,
            question="合成关系认识：先看原文，再连接任务与交付。",
        )
        source = mapped["results"][0]
        assert source["result"]["status"] == "completed"
        original = deepcopy(source["result"]["work_map"])
        calls = len(model.contexts)
        values = {
            "source_step_id": source["step_id"],
            "source_relation_index": 0,
            "question_id": qid,
            "previous_view": "合成旧理解：产物相似可能意味着责任相同。",
            "observation": "原文只连接具体任务与产物，未说明个人验收权限。",
            "current_view": "合成新理解：先保留本场景的任务产出关系，不外推个人验收权。",
            "open_question": "真实的责任边界与迁移条件仍需核实。",
        }
        noted = save(base + "/insights", values)
        note = noted["insights"][-1]
        assert len(model.contexts) == calls
        assert noted["results"][0]["result"]["work_map"] == original
        page = client.get("/api/career/work-relations", params={"goal_id": goal["id"]}).json()
        relation = next(row for row in page["relations"] if row["relation_index"] == 0)
        assert relation["personal_notes"][0]["current_view"] == values["current_view"]
        assert "personal_notes" not in next(
            row for row in page["relations"] if row["relation_index"] == 1
        )
        project = client.get("/api/projects/" + goal["id"]).json()
        store = ResearchStore(tmp_path / "checkpoints.db", namespace=str(database.resolve()))
        notebook = LearningNotebook(lambda: project, store)
        recalled = notebook.read(note["id"])["note"]
        assert recalled["source_relation"]["relation"] == original["work_relations"][0]
        assert [row["index"] for row in recalled["source_relation"]["claims"]] == [0, 1]
        assert len(recalled["source_locators"]) == 1
        old = notebook.read_research_history(source["step_id"])["research"]
        assert old["work_map_then"] == original
        assert old["current_relation_notes"][0]["id"] == note["id"]
        for changes in (
            {"source_relation_index": 99},
            {"source_claim_index": 0},
            {"source_relation_index": True},
        ):
            response = client.post(base + "/insights", headers=auth, json={**values, **changes})
            assert response.status_code == 422
        assert len(client.get(base).json()["insights"]) == 1
        checked = run_stage(
            client,
            goal["id"],
            auth,
            "ask",
            question_id=qid,
            insight_id=note["id"],
            question="结合我的关系认识回读原文，核对迁移边界。",
        )
        result = checked["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert len(result["evidence"]) == 1
        saved_origin = model.contexts[-1]["project_context"]["career_evidence"][
            "selected_learning_note"
        ]["source_relation"]
        assert saved_origin["relation"] == original["work_relations"][0]
        save(base + "/insights/" + note["id"] + "/use", {"use_for_research": False})
        project = client.get("/api/projects/" + goal["id"]).json()
        assert (
            "current_relation_notes"
            not in notebook.read_research_history(source["step_id"])["research"]
        )
        assert notebook.search(["合成新理解"])["matching_count"] == 0
