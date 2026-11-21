"""Work explanation and mapping can find old work originals without using personal records."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class WorkLibraryModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage = [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        assert "list_archived_sources" in {row["name"] for row in self.tools}
        assert not context.get("application_background")
        personal = context["project_context"]["career_evidence"]
        assert not personal.get("stories") and not personal.get("resume")
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "list_archived_sources", {"offset": 20}
        elif len(outputs) == 1:
            assert "evidence" not in outputs[-1]
            assert outputs[-1]["total"] == 25 and outputs[-1]["next_offset"] is None
            source = next(row for row in outputs[-1]["documents"]
                          if row["title"] == "合成早期工作原文")
            assert "quote" not in source and source["title_not_evidence"]
            name, args = "read_archived_document", {
                "document_id": source["id"], "start": 0,
            }
        else:
            evidence = outputs[-1]["evidence"]
            assert any("验收权仍未知。" in row["quote"] for row in evidence)
            claims = [{"category": category, "basis": "direct", "text": text,
                       "requirement": "unspecified", "evidence_ids": [evidence[0]["id"]]}
                      for category, text in [("task", "核对回填账本"), ("deliverable", "差异清单")]]
            name, args = "finish_research", {"claims": claims,
                "gaps": ["用户提供的工作说明未独立核实，验收权仍未知。"]}
            if context["project_context"]["career_action"] == "map":
                args.update(work_map={"version": "work-map-v3-work-relations",
                    "scope_note": "合成工作资料示例，未选择JD，不证明招聘资格或个人能力。",
                    "work_types": [{"name": "局部账本核对", "problem": "找出回填差异。",
                        "tasks": "核对回填账本", "deliverables": "差异清单",
                        "claim_indices": [0, 1], "basis": "inference",
                        "boundary": "只解释原文列出的局部工作。",
                        "next_check": "验收权仍需核对。"}],
                    "work_relations": [{"source_claim_index": 0, "target_claim_index": 1,
                        "predicate": "produces", "basis": "inference",
                        "rationale": "同一份说明列出任务与交付物。",
                        "transfer_limit": "不能外推生产责任或个人胜任。"}],
                    "comparisons": [], "unknowns": ["验收权仍未知。"]}, revisions=[])
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("kind", ["role", "map"])
def test_work_understanding_searches_full_work_library_without_private_inputs(tmp_path, kind):
    database = tmp_path / "work-library.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = WorkLibraryModel()
    with TestClient(create_app(settings, model=model, reports_dir=tmp_path / "reports"),
                    base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text
        )[1]}

        def save(path, data):
            response = client.post(path, headers=auth, json=data)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成：完整工作资料库", "goal": "理解工作线",
                    "background": "个人背景不作为工作职责依据。",
                    "resume_text": "个人简历中也有回填账本，不作为本轮工作原文。",
                    "material_title": "合成早期工作原文",
                    "material_text": "任务：核对回填账本。交付：差异清单。验收权仍未知。"})
        identity = goal["id"]
        base = "/api/career/" + identity
        original = goal["materials"][0]["id"]
        private = {goal["resume"]["document_id"]}
        story = save(base + "/stories", {"title": "合成个人记录",
                     "situation": "本地回填账本", "action": "只构造样例。",
                     "result": "尚无生产结果。", "limits": "不能证明工作职责。"})["stories"][0]
        private.add(story["document_id"])
        for index in range(24):
            save(base + "/materials", {"title": f"合成较新背景说明{index}", "text":
                "业务工作资料、实际任务、交付物、能力、工具与责任边界，需要原文条件与引用。"
                "用户提供的记录不证明岗位职责或招聘资格，未说明的内容保留未知，按问题核对。"})
        foreign = save("/api/career", {"title": "其他合成目标", "goal": "保持资料范围",
                       "material_title": "其他目标的回填账本", "material_text": "回填账本。"})
        before = client.get(base).json()
        row = run_stage(client, identity, auth, kind)["results"][0]
        result = row["result"]
        assert result["status"] == "completed", result.get("stop_reason")
        assert original not in {item["id"] for item in result["scope"]["public_document_titles"]}
        assert original not in result["scope"]["selected_public_document_ids"]
        assert set(result["scope"]["archived_public_ids"]) == set(before["document_ids"]) - private
        assert foreign["materials"][0]["id"] not in result["scope"]["archived_public_ids"]
        assert {item["public_document_id"] for item in result["evidence"]} == {original}
        assert result["model_calls"] == 3
        assert all(item["requirement"] == "unspecified" for item in result["claims"])
        if kind == "map":
            assert len(result["work_map"]["work_relations"]) == 1
        after = client.get(base).json()
        for key in ("stories", "tasks", "questions", "insights", "document_ids"):
            assert after[key] == before[key]
