"""Recall a map-only limit, read the complete old map, then reread the scoped original."""

import json
import re
from copy import deepcopy

from starlette.testclient import TestClient
from test_career_material_map import MATERIALS
from test_career_work_relations import LIMIT, RelationsBrowserModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

QUERY = "合成图谱记忆：核对以前保存的迁移限定，再用本轮可用原文检查。"


class MapRecallModel(ModelClient):
    def __init__(self):
        self.initial = RelationsBrowserModel()
        self.contexts, self.last_usage = [], {}
        self.missing_source = False
        self.expected_step = None
        self.original_id = None

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        if context["project_context"]["career_action"] == "map":
            self.initial.tools = self.tools
            return await self.initial.turn(history)
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "search_research_history", {"terms": ["末尾迁移前提"], "offset": 0}
        elif len(outputs) == 1:
            assert outputs[0]["matching_count"] == 1
            found = outputs[0]["research"][0]
            assert found["map_match_count"] == 14 and not found["claim_previews"]
            assert found["map_previews"][0]["section"] == "relation"
            assert found["map_previews"][0]["matched_fields"] == ["transfer_limit"]
            assert found["map_previews"][0]["preview_is_partial"]
            if self.expected_step:
                assert found["step_id"] == self.expected_step
            name, args = "read_research_history", {"step_id": found["step_id"]}
        elif len(outputs) == 2:
            record = outputs[-1]["research"]
            last = record["work_map_then"]["work_relations"][-1]
            assert last["transfer_limit"] == LIMIT + "13"
            claim = record["claim_details_to_recheck"][last["source_claim_index"]]
            source = claim["source_references_to_reread"][0]
            self.original_id = source["public_document_id"]
            scope = context["fixed_scope"]
            assert self.original_id not in {row["id"] for row in scope["public_document_titles"]}
            assert source["in_current_scope"] is not self.missing_source
            assert "evidence_ids" not in json.dumps(record)
            assert all("quote" not in row and "id" not in row
                       for row in record["source_references_to_reread"])
            document = scope["public_document_titles"][0]["id"] if self.missing_source else (
                self.original_id
            )
            name, args = "read_archived_document", {"document_id": document, "start": 0}
        else:
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference", "requirement": "unspecified",
                            "text": "旧原文已移出本轮，目录资料不足以重核原工作关系。"
                            if self.missing_source else
                            "合成复核：旧关系的迁移限定仍需保留，原文未说明真实验收权。",
                            "evidence_ids": [row["id"] for row in outputs[-1]["evidence"]]}],
                "gaps": ["旧原文不可读，保留无法重核。"] if self.missing_source else [
                    "真实分工与验收权限仍需另外核实。",
                ],
            }
            if context["project_context"].get("previous_findings") or (
                context["project_context"].get("historical_reply")
            ):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_agent_recalls_map_only_limits_without_restoring_removed_sources(tmp_path):
    database = tmp_path / "map-memory.db"
    upgrade(database)
    model = MapRecallModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {"title": "合成图谱记忆", "goal": "按旧地图限定回读原文"})
        base = "/api/career/" + goal["id"]
        sources = []
        for title, task, deliverable in MATERIALS:
            saved = post(base + "/materials", {
                "title": title, "text": f"任务：{task}。交付：{deliverable}。验收权仍未知。",
            })
            sources.append(saved["materials"][-1]["id"])
        original = run_stage(client, goal["id"], auth, "map", material_ids=sources,
                             question="合成关系库长页：任务与对应的交付物。")
        source = original["results"][0]
        assert source["result"]["status"] == "completed"
        model.expected_step = source["step_id"]
        for index in range(22):
            post(base + "/materials", {"title": f"合成图谱记忆目录{index}",
                                       "text": QUERY + "仅为虚构目录背景，不说明具体岗位。"})
        before = deepcopy(client.get(base).json())
        remembered = run_stage(client, goal["id"], auth, "ask", question=QUERY)
        result = remembered["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert result["model_calls"] == 4
        context = result["career_learning_context"]
        assert context["history_searches"][0]["map_match_count"] == 14
        assert context["read_history"][0]["work_map_then"] == source["result"]["work_map"]
        assert {row["public_document_id"] for row in result["evidence"]} == {model.original_id}
        assert [row["tool"] for row in result["trace"]] == [
            "search_research_history", "read_research_history", "read_archived_document",
            "finish_research",
        ]
        assert result["trace"][0]["map_matches"] == 14
        assert remembered["document_ids"] == before["document_ids"]
        assert remembered["questions"] == before["questions"] and not remembered["insights"]
        assert client.delete(base + "/materials/" + model.original_id,
                             headers=auth).status_code == 200
        model.missing_source = True
        limited = run_stage(client, goal["id"], auth, "ask", question=QUERY)
        last = limited["results"][0]["result"]
        assert last["status"] == "completed", last.get("stop_reason")
        assert any("无法重核" in gap for gap in last["gaps"])
        assert model.original_id not in limited["document_ids"]
        assert all(row.get("public_document_id") != model.original_id for row in last["evidence"])
        assert last["career_learning_context"]["read_history"][0]["work_map_then"] == (
            source["result"]["work_map"]
        )
        retained = next(row for row in limited["results"] if row["step_id"] == source["step_id"])
        assert retained["result"]["work_map"] == source["result"]["work_map"]
        assert not limited["questions"] and not limited["insights"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = client.get(base).json()
        assert restored["results"][0]["result"]["career_learning_context"] == (
            last["career_learning_context"]
        )
