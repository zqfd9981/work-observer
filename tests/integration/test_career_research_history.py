"""The agent can recall an old analysis, then reread an attached original outside previews."""

import json
import re
from copy import deepcopy

import pytest
from starlette.testclient import TestClient
from test_career_claim_recheck import LONG_CLAIM, ClaimRecheckModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade

QUERY = "合成历史回忆：找回以前的解释，再用本轮可用原文核对。"


class ResearchHistoryModel(ModelClient):
    def __init__(self):
        self.initial = ClaimRecheckModel()
        self.contexts, self.last_usage = [], {}
        self.cite_history = False
        self.missing_source = False
        self.expected_step = None

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        if personal["selected_material"]:
            self.initial.tools = self.tools
            return await self.initial.turn(history)
        assert {"search_research_history", "read_research_history"} <= {
            row["name"] for row in self.tools
        }
        assert not personal.get("continued_discussion") and not personal["learning_notes"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "search_research_history", {"terms": ["末尾限定"], "offset": 0}
        elif len(outputs) == 1:
            found = outputs[0]["research"]
            assert outputs[0]["matching_count"] == 1
            assert found[0]["claim_previews"][0]["position"] == 24
            assert found[0]["claim_previews"][0]["preview_is_partial"]
            if self.expected_step:
                assert found[0]["step_id"] == self.expected_step
            name, args = "read_research_history", {"step_id": found[0]["step_id"]}
        elif len(outputs) == 2:
            record = outputs[-1]["research"]
            assert record["claim_details_to_recheck"][-1]["text"] == LONG_CLAIM
            assert record["claim_details_to_recheck"][-1]["position"] == 24
            assert "evidence_ids" not in json.dumps(record)
            refs = record["source_references_to_reread"]
            assert all("quote" not in row and "id" not in row for row in refs)
            original = refs[0]["public_document_id"]
            scope = context["fixed_scope"]
            assert original not in {row["id"] for row in scope["public_document_titles"]}
            assert refs[0]["in_current_scope"] is not self.missing_source
            if self.missing_source:
                assert original not in scope["archived_public_ids"]
                document = scope["public_document_titles"][0]["id"]
            else:
                document = original
            name, args = "read_archived_document", {"document_id": document, "start": 0}
        else:
            evidence = outputs[2]["evidence"]
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "inference",
                            "requirement": "unspecified", "text": (
                                "合成补充说明仅记录局部观察，未说明实际生产权限。"
                                if self.missing_source else
                                "合成回忆核对：旧第24条需保留仅局部样例的限定，生产权限仍未知。"
                            ), "evidence_ids": [outputs[1]["research"]["step_id"]]
                            if self.cite_history else [
                                row["id"] for row in evidence
                            ]}],
                "gaps": ["旧原文已移出本轮，无法重核旧判断。"] if self.missing_source else [
                    "旧分析不是新证据，局部解释仍需结合实际分工核对。",
                ],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_agent_recalls_complete_old_research_and_returns_to_current_originals(tmp_path):
    database = tmp_path / "research-history.db"
    upgrade(database)
    model = ResearchHistoryModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, payload):
            response = client.post(path, headers=auth, json=payload)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成研究历史回查", "goal": "用当前原文核对旧解释",
            "material_title": "合成历史记忆原资料",
            "material_text": "虚构工作说明：只记录局部请求样例，实际生产权限未说明。",
        })
        identity, original = goal["id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        source = run_stage(client, identity, auth, "ask", question="合成原分析。",
                           material_id=original)["results"][0]
        assert source["result"]["status"] == "completed"
        model.expected_step = source["step_id"]
        for index in range(21):
            post(base + "/materials", {"title": f"合成最近背景{index}",
                 "text": QUERY + "虚构补充：只记录局部观察，实际生产权限未说明。"})
        foreign = post("/api/career", {"title": "合成其他目标", "goal": "独立的研究范围",
                       "material_title": "其他原文", "material_text": "只属于另一个目标。"})
        foreign_study = run_stage(client, foreign["id"], auth, "ask", question="独立旧研究。",
                                  material_id=foreign["materials"][0]["id"])["results"][0]
        assert foreign_study["result"]["status"] == "completed"
        before = deepcopy(client.get(base).json())
        remembered = run_stage(client, identity, auth, "ask", question=QUERY)["results"][0]
        result = remembered["result"]
        assert result["status"] == "completed", json.dumps({
            key: result.get(key) for key in ("stop_reason", "trace", "model_calls")
        }, ensure_ascii=False)
        assert result["model_calls"] == 4
        saved = result["career_learning_context"]
        assert saved["history_searches"][0]["returned_step_ids"] == [source["step_id"]]
        assert saved["read_history"][0]["claim_details_to_recheck"][-1]["text"] == LONG_CLAIM
        assert saved["read_history"][0]["source_references_to_reread"][0]["in_current_scope"]
        assert {row["public_document_id"] for row in result["evidence"]} == {original}
        assert [row["tool"] for row in result["trace"][:3]] == [
            "search_research_history", "read_research_history", "read_archived_document",
        ]
        model.cite_history = True
        rejected = run_stage(client, identity, auth, "ask", question=QUERY)["results"][0]
        assert rejected["result"]["status"] != "completed" and not rejected["result"]["claims"]
        model.cite_history = False
        assert client.delete(base + "/materials/" + original, headers=auth).status_code == 200
        model.missing_source = True
        limited = run_stage(client, identity, auth, "ask", question=QUERY)["results"][0]
        assert limited["result"]["status"] == "completed", limited["result"].get("stop_reason")
        assert any("无法重核" in gap for gap in limited["result"]["gaps"])
        assert not limited["result"]["career_learning_context"]["read_history"][0][
            "source_references_to_reread"][0]["in_current_scope"]
        after = client.get(base).json()
        assert original not in after["document_ids"]
        assert after["insights"] == before["insights"] == []
        retained = next(row for row in after["results"] if row["step_id"] == source["step_id"])
        assert retained["result"]["claims"] == source["result"]["claims"]
        assert retained["result"]["evidence"] == source["result"]["evidence"]
        assert not after["questions"]


def test_history_notebook_pages_only_eligible_owned_research_and_copies_full_limits():
    result = {"status": "completed", "claims": [{"text": LONG_CLAIM, "basis": "inference",
              "requirement": "preferred", "category": "task", "evidence_ids": ["old-cite"]}],
              "evidence": [{"id": "old-cite", "title": "Old source", "quote": "Old quote",
                            "public_document_id": "raw", "start": 0, "end": 9}],
              "gaps": ["Still unknown."], "work_map": {"scope_note": "Full old map limit."}}
    runs = {str(index): {"state": "completed", "result": deepcopy(result)} for index in range(9)}
    runs["7"]["state"] = "invalidated"
    runs["8"]["result"]["business_review"] = {"status": "rejected"}
    project = {"career": {"runs": [{"step_id": str(index), "kind": "ask",
               "created_at": str(index), "user_question": "Old inquiry"} for index in range(9)]},
               "steps": [{"id": str(index), "run_id": str(index), "state": "completed"}
                         for index in range(9)]}
    store = type("Store", (), {"get": lambda self, identity: runs[identity]})()
    notebook = LearningNotebook(lambda: project, store)
    first = notebook.search_research_history([], offset=0)
    assert first["matching_count"] == 7 and first["next_offset"] == 6
    assert len(notebook.search_research_history([], offset=6)["research"]) == 1
    old = notebook.read_research_history("0")["research"]
    assert old["claim_details_to_recheck"][0]["text"] == LONG_CLAIM
    assert old["claim_details_to_recheck"][0]["requirement"] == "preferred"
    assert "quote" not in old["source_references_to_reread"][0]
    old["work_map_then"]["scope_note"] = "Changed returned object only"
    assert runs["0"]["result"]["work_map"]["scope_note"] == "Full old map limit."
    for key in ("7", "8", "another-goal-step"):
        with pytest.raises(ProbeError, match="RESEARCH_HISTORY_NOT_AVAILABLE"):
            notebook.read_research_history(key)
