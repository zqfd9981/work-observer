"""A user's source-linked correction remains available when continuing old research."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

LONG_CLAIM = "🧪" * 1100 + "末尾限定：仅局部资料，验收权未明确。"
CORRECTION = "局部观察只能说明给定输入；它不确认业务验收权、并发或生产职责。"


class ClaimCorrectionModel(ModelClient):
    def __init__(self):
        self.expected_note_id = None
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        continued = personal.get("continued_discussion")
        if continued:
            notes = personal["learning_notes"]
            assert notes and notes[0]["current_user_view"] == CORRECTION
            if self.expected_note_id:
                assert notes[0]["id"] == self.expected_note_id
            assert notes[0]["original_analysis"]["text"] == LONG_CLAIM
            assert personal["learning_recall"]["selections"][0]["reason"] == "same_discussion"
            assert "用户的修正同样不是已验证事实" in history[0]["content"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            source = next(row for row in context["fixed_scope"]["public_document_titles"]
                          if row["title"].startswith("合成纠正原文"))
            name, args = "read_archived_document", {"document_id": source["id"], "start": 0}
        else:
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "inference",
                            "requirement": "unspecified", "text": (
                                "合成后续：原文只有局部样例，验收权限仍未知。"
                                if continued else LONG_CLAIM
                            ), "evidence_ids": [row["id"] for row in outputs[0]["evidence"]]}],
                "gaps": ["真实业务范围与运行职责仍需核实。"],
            }
            if context["project_context"].get("previous_findings") or context[
                "project_context"
            ].get("historical_reply"):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_corrected_claim_follows_continued_discussion_across_sessions(tmp_path):
    database = tmp_path / "claim-correction.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = ClaimCorrectionModel()
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成判断纠正", "goal": "保留来源，回查个人修正",
            "material_title": "合成纠正原文",
            "material_text": "合成说明只记录局部样例。实际业务验收权、并发和生产职责未说明。",
        })
        identity = goal["id"]
        base = "/api/career/" + identity
        source = run_stage(client, identity, auth, "ask", question="接口工作 adapter workflow")
        original = source["results"][0]
        assert original["result"]["status"] == "completed"
        assert original["question_id"] is None
        corrected = post(base + "/insights", {
            "previous_view": "Agent原判断较长，完整原句保留在来源中。",
            "observation": "原文只写局部样例，生产责任和验收权未说明。",
            "current_view": CORRECTION, "open_question": "真实运行条件尚需核实。",
            "source_step_id": original["step_id"], "source_claim_index": 0,
        })
        correction = corrected["insights"][-1]
        model.expected_note_id = correction["id"]
        for index in range(8):
            post(base + "/insights", {
                "previous_view": "接口工作 adapter workflow",
                "observation": "合成记录，不是执行验证。",
                "current_view": f"接口工作 adapter workflow，其他认识{index}。",
            })
        snapshot = client.get(base).json()
        reply = run_stage(client, identity, auth, "ask", question="继续接口工作 adapter workflow",
                          source_step_id=original["step_id"])["results"][0]
        assert reply["result"]["status"] == "completed", reply["result"]
        recalled = reply["result"]["career_learning_context"]["notes"]
        assert recalled[0]["id"] == correction["id"]
        assert recalled[0]["original_analysis"]["text"] == LONG_CLAIM
        following = run_stage(client, identity, auth, "ask", question="再说明 adapter workflow",
                              source_step_id=reply["step_id"])["results"][0]
        assert following["result"]["status"] == "completed", following["result"]
        assert following["result"]["career_learning_context"]["notes"][0]["id"] == correction["id"]
        after = client.get(base).json()
        assert after["insights"] == snapshot["insights"]
        assert after["document_ids"] == snapshot["document_ids"] and not after["tasks"]
        stored = next(row for row in after["results"] if row["step_id"] == original["step_id"])
        assert stored["result"] == original["result"]
    with TestClient(create_app(settings, model=model), base_url="http://127.0.0.1") as client:
        saved = client.get(base).json()
        history = next(row for row in saved["results"] if row["step_id"] == reply["step_id"])
        assert history["result"]["career_learning_context"]["notes"] == recalled
        assert saved["insights"][0]["current_view"] == CORRECTION
