"""Cross-goal recall supplies old context while current evidence scope stays unchanged."""

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

MARKER = "合成跨岗线索"
NOTE = MARKER + "：同一工具下还需区分业务对象和验收条件。" * 48 + "末尾：旧场景未证明新岗位权限。"


class OtherGoalMemoryModel(ModelClient):
    def __init__(self):
        self.initial = ClaimRecheckModel()
        self.last_usage, self.contexts = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        if "合成跨目标复用" not in context["question"]:
            self.initial.tools = self.tools
            return await self.initial.turn(history)
        self.contexts.append(context)
        assert {"search_other_goal_memory", "read_other_goal_memory"} <= {
            row["name"] for row in self.tools
        }
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            calls = [("search_other_goal_memory", {"terms": [MARKER], "offset": 0})]
        elif len(outputs) == 1:
            found = outputs[0]["memories"]
            assert len(found) == 2 and {row["kind"] for row in found} == {"insight", "research"}
            assert outputs[0]["matching_count"] == 2
            row = next(row for row in found if row["kind"] == "insight")
            calls = [("read_other_goal_memory", {key: row[key] for key in (
                "project_id", "kind", "record_id",
            )})]
        elif len(outputs) == 2:
            row = next(row for row in outputs[0]["memories"] if row["kind"] == "research")
            calls = [("read_other_goal_memory", {key: row[key] for key in (
                "project_id", "kind", "record_id",
            )})]
        elif len(outputs) == 3:
            note, research = outputs[1]["memory"], outputs[2]["memory"]
            assert note["current_user_view"] == NOTE
            assert research["claim_details_to_recheck"][-1]["text"] == LONG_CLAIM
            assert "evidence_ids" not in json.dumps(research)
            refs = research["source_references_to_reread"]
            assert not any(row["in_current_scope"] for row in refs)
            allowed = context["fixed_scope"]["archived_public_ids"]
            assert all(row["public_document_id"] not in allowed
                       for row in refs)
            current = context["fixed_scope"]["public_document_titles"][0]["id"]
            calls = [("read_archived_document", {"document_id": current, "start": 0})]
        else:
            calls = [("finish_research", {
                "claims": [{"category": "task", "basis": "inference",
                            "requirement": "unspecified",
                            "text": "旧场景的解释只供比较；新资料没有明确个人验收权限，仍需核实。",
                            "evidence_ids": [row["id"] for row in outputs[-1]["evidence"]]}],
                "gaps": ["来源目标的原文不在本轮范围，旧解释未重新核实。"],
            })]
        messages = [{"type": "function_call", "name": name, "arguments": json.dumps(args),
                     "call_id": str(len(history)) + ":" + str(index)}
                    for index, (name, args) in enumerate(calls)]
        return messages, messages[0]


def test_agent_recalls_other_goal_without_copying_notes_or_expanding_raw_scope(tmp_path):
    database = tmp_path / "other-goal-memory.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = OtherGoalMemoryModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        source = save("/api/career", {"title": "合成旧工作场景", "goal": "解释局部样例",
                      "material_title": "合成旧工作原文",
                      "material_text": "只记录局部样例，权限未知。"})
        old = run_stage(client, source["id"], auth, "ask", question=MARKER + "的原分析。",
                        material_id=source["materials"][0]["id"])["results"][0]
        assert old["result"]["status"] == "completed"
        base = "/api/career/" + source["id"]
        values = {"previous_view": "共用工具就可以迁移。", "observation": "旧工作场景中的自述。",
                  "current_view": NOTE, "open_question": "新场景中由谁验收？",
                  "source_step_id": old["step_id"], "source_claim_index": 23}
        save(base + "/insights", values)
        hidden = save(base + "/insights", {**values, "current_view": MARKER + "已搁置的旧认识。"})[
            "insights"][-1]
        save(base + "/insights/" + hidden["id"] + "/use", {"use_for_research": False})
        before_source = client.get(base).json()
        target = save("/api/career", {"title": "合成新工作场景", "goal": "检查迁移条件",
                      "material_title": "合成新工作原文",
                      "material_text": "新场景记录交付对象，不明确个人验收权限。"})
        remembered = run_stage(client, target["id"], auth, "ask", question="合成跨目标复用："
                               + MARKER + "在新工作中还成立吗？")["results"][0]
        result = remembered["result"]
        assert result["status"] == "completed", json.dumps({key: result.get(key) for key in (
            "stop_reason", "trace", "model_calls",
        )}, ensure_ascii=False)
        assert result["model_calls"] == 5
        reads = result["career_learning_context"]["read_other_goals"]
        assert len(reads) == 2 and all(row["project_id"] == source["id"] for row in reads)
        assert {row["public_document_id"] for row in result["evidence"]} == {
            target["materials"][0]["id"],
        }
        assert client.get(base).json() == before_source
        after = client.get("/api/career/" + target["id"]).json()
        assert after["document_ids"] == target["document_ids"] and not after["insights"]
        assert not after["questions"] and not after["tasks"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        reopened = client.get("/api/career/" + target["id"]).json()["results"][0]
        assert reopened["result"]["career_learning_context"]["read_other_goals"] == reads
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]}
        erased = client.delete("/api/projects/" + source["id"], headers=auth)
        assert erased.status_code == 200, erased.text
        assert target["id"] in erased.json()["affected_project_ids"]
        forgotten = client.get("/api/projects/" + target["id"]).json()
        assert forgotten["stop_reason"] == "project_forgotten"
        assert not forgotten.get("career") and not forgotten["steps"]


def test_other_goal_memory_pages_all_goals_and_excludes_shelved_or_forgotten_records():
    notes = [{"id": str(index), "previous_view": "之前", "observation": "观察",
              "current_view": "共同关键词，条件" + str(index), "open_question": "仍未知",
              "created_at": str(index), "use_for_research": index != 8} for index in range(9)]
    other = {"id": "other", "title": "其他目标", "goal": "旧场景",
             "career": {"insights": notes, "runs": []}, "steps": []}
    current = {**deepcopy(other), "id": "current"}
    forgotten = {"id": "forgotten", "title": "已忘记", "state": "invalidated"}
    notebook = LearningNotebook(lambda: current, None,
                                project_lister=lambda: [current, other, forgotten])
    before = deepcopy(other)
    first = notebook.search_other_goal_memory(["共同关键词"])
    assert first["matching_count"] == 8 and first["next_offset"] == 6
    second = notebook.search_other_goal_memory(["共同关键词"], offset=6)
    assert len(first["memories"]) == 6 and len(second["memories"]) == 2
    assert len({row["record_id"] for row in first["memories"] + second["memories"]}) == 8
    recalled = notebook.read_other_goal_memory("other", "insight", "0")
    recalled["memory"]["current_user_view"] = "只改返回值"
    assert other == before
    for identity, record_id in [("current", "0"), ("forgotten", "0"), ("other", "8")]:
        with pytest.raises(ProbeError):
            notebook.read_other_goal_memory(identity, "insight", record_id)


def test_cross_goal_map_search_finds_complete_transfer_limits_beyond_preview():
    limit = "原场景条件需要逐项核对。" * 60 + "跨场景工作边界：个人验收权仍未知。"
    work_map = {"scope_note": "只讨论两份旧工作材料。", "work_relations": [{
        "source_kind": "tool", "source_text": "同名工具", "target_kind": "task",
        "target_text": "记录业务对象", "relation": "supports", "basis": "inference",
        "rationale": "工具用途与工作对象相关。", "transfer_limit": limit, "claim_indices": [0],
    }]}
    result = {"status": "completed", "claims": [], "evidence": [], "gaps": [],
              "work_map": work_map}
    source = {"id": "source", "title": "原工作对象", "goal": "解释局部关系",
              "career": {"runs": [{"step_id": "map", "kind": "map", "created_at": "1"}]},
              "steps": [{"id": "map", "run_id": "run", "state": "completed"}]}
    store = type("Store", (), {"get": lambda self, key: {
        "state": "completed", "result": result,
    }})()
    notebook = LearningNotebook(lambda: {"id": "current"}, store,
                                project_lister=lambda: [source])
    found = notebook.search_other_goal_memory(["跨场景工作边界"])["memories"]
    assert len(found) == 1 and found[0]["preview"]["map_match_count"] == 1
    assert found[0]["preview"]["map_previews"][0]["preview_is_partial"]
    full = notebook.read_other_goal_memory("source", "research", "map")["memory"]
    assert full["work_map_then"]["work_relations"][0]["transfer_limit"] == limit
