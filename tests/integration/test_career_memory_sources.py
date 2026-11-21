"""A remembered understanding can lead back to an older attached original, beyond previews."""

import json
import re

from starlette.testclient import TestClient
from test_career_question_materials import QuestionMaterialModel
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class MemorySourceModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}
        self.initial = QuestionMaterialModel()

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        personal = context["project_context"]["career_evidence"]
        if personal["selected_material"]:
            self.initial.tools = self.tools
            return await self.initial.turn(history)
        notes = personal["learning_notes"]
        assert len(notes) == 1 and notes[0]["source_locators"]
        original = notes[0]["source_locators"][0]["public_document_id"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "search_archived_sources", {"terms": ["请求编号"]}
        elif len(outputs) == 1:
            matches = [row for row in outputs[-1]["evidence"]
                       if row.get("public_document_id") == original]
            assert matches, "The remembered original is missing from searchable sources"
            name, args = "read_archived_document", {"document_id": original, "start": 0}
        else:
            evidence = outputs[-1]["evidence"]
            assert any("最终条件：只能描述局部流程，验收权仍未知。" in row["quote"]
                       for row in evidence)
            name, args = "finish_research", {
                "claims": [{"category": "business", "basis": "inference",
                            "requirement": "unspecified", "text":
                            "合成旧操作原文保留局部流程与验收权未知的限制，不能由一次返回结果确定责任。",
                            "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": ["个人认识仍需对照实际分工，旧笔记不是独立证据。"],
            }
            if context["project_context"].get("previous_findings") or context[
                "project_context"].get("historical_reply"):
                args["revisions"] = []
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


def test_recalled_understanding_can_search_and_reread_an_original_outside_initial_previews(
    tmp_path,
):
    database = tmp_path / "memory-sources.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = MemorySourceModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        book = save("/api/career", {"title": "合成：记忆回查工作原文", "goal": "持续理解系统边界",
                    "material_title": "合成旧操作原文", "material_text":
                    "异常处理应留存请求编号，返回结果不直接说明责任归属。"
                    "最终条件：只能描述局部流程，验收权仍未知。"})
        identity = book["id"]
        base = "/api/career/" + identity
        original = book["materials"][0]["id"]
        study = run_stage(client, identity, auth, "ask", question="合成原文建档：说明操作边界。",
                          material_id=original)["results"][0]
        note = save(base + "/insights", {
            "previous_view": "返回成功可能意味着有完整责任。", "observation": "阅读合成工作说明。",
            "current_view": "关于系统边界的当前认识仍待核实，验收责任不能由一次返回结果推出。",
            "open_question": "系统边界在哪些条件下需要重新核对？",
            "source_step_id": study["step_id"], "source_claim_index": 0,
        })["insights"][-1]
        query = "合成记忆原文复查：系统边界这条旧认识有哪些条件需要保留？"
        for index in range(24):
            save(base + "/materials", {"title": f"合成后续概念说明{index}", "text": query})
        foreign = save("/api/career", {"title": "另一个合成目标", "goal": "独立资料范围",
                       "material_title": "外部目标的同词原文", "material_text": "请求编号。"})
        foreign_document = foreign["materials"][0]["id"]
        before = client.get(base).json()

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}
        data = run_stage(client, identity, auth, "ask", question=query)
        result = data["results"][0]["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        scope = result["scope"]
        assert original not in scope["selected_public_document_ids"]
        assert original not in {row["id"] for row in scope["public_document_titles"]}
        assert original in scope["archived_public_ids"]
        assert foreign_document not in scope["archived_public_ids"]
        assert set(scope["archived_public_ids"]) == set(before["document_ids"])
        assert {ev["public_document_id"] for ev in result["evidence"]} == {original}
        assert result["model_calls"] == 3
        assert result["career_learning_context"]["notes"][0]["id"] == note["id"]
        for key in ("questions", "tasks", "insights", "document_ids"):
            assert data[key] == before[key]
