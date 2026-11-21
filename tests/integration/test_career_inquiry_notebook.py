"""The agent can use collected counterexamples before an inquiry has any research runs."""

import json
import re
from copy import deepcopy

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import ModelClient
from work_observer.research.learning import LearningNotebook
from work_observer.storage.database import upgrade

ANNOTATION = "需要区分原句、适用条件和用户自己的推断。" * 30 + "证据校正：末尾仍需核实业务验收权。"
OLD_QUESTION = "合成旧调查：配置与复杂集成分别交付什么？" * 35 + "末尾限定：任务对象可能不同。"
RAW = "复杂集成需要适配接口与回归检查。局部说明未写明业务验收权限。"


class InquiryNotebookModel(ModelClient):
    def __init__(self):
        self.contexts, self.tools, self.last_usage = [], [], {}

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        assert {"search_inquiries", "read_inquiry"} <= {row["name"] for row in self.tools}
        assert context["project_context"]["career_evidence"]["selected_inquiry"] is None
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if not outputs:
            name, args = "search_inquiries", {"terms": ["证据校正"], "offset": 0}
        elif len(outputs) == 1:
            assert outputs[-1]["next_offset"] == 6
            name, args = "search_inquiries", {"terms": ["证据校正"], "offset": 6}
        elif len(outputs) == 2:
            selected = outputs[-1]["inquiries"][0]
            assert selected["preview_is_partial"] and selected["state"] == "parked"
            assert any(field.startswith("passage_") for field in selected["matched_fields"])
            name, args = "read_inquiry", {"question_id": selected["id"]}
        elif len(outputs) == 3:
            inquiry = outputs[-1]["inquiry"]
            assert inquiry["question"] == OLD_QUESTION
            assert not inquiry["linked_research_step_ids"]
            passage = inquiry["evidence_passages"][0]
            assert passage["user_note"] == ANNOTATION and passage["quote"] == RAW
            assert passage["target_view"] == inquiry["hypothesis_a"]
            assert passage["relation"] == "challenges" and "evidence" not in outputs[-1]
            source = passage if passage["in_current_scope"] else inquiry["source_passage"]
            assert source["in_current_scope"]
            name, args = "read_archived_document", {
                "document_id": source["public_document_id"], "start": source["start"],
            }
        else:
            passage = outputs[2]["inquiry"]["evidence_passages"][0]
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "synthesis",
                            "requirement": "unspecified", "text": (
                                "合成反例说明复杂集成需要接口适配与回归检查，验收权仍未知。"
                                if passage["in_current_scope"] else
                                "合成当前原文只说明给定配置范围；旧反例资料本轮不在范围内，无法重核。"
                            ), "evidence_ids": [row["id"] for row in outputs[-1]["evidence"]]}],
                "gaps": ["用户的反例标注是否只是适用条件不同，业务验收范围仍需查证。"],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("remove_source", [False, True])
def test_agent_recalls_unstudied_inquiry_annotations_and_reads_only_current_sources(
    tmp_path, remove_source,
):
    database = tmp_path / "inquiry-notebook.db"
    upgrade(database)
    model = InquiryNotebookModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def post(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = post("/api/career", {
            "title": "合成未研究的调查回忆", "goal": "先找回标注，再核对完整原文",
            "material_title": "合成调查起点",
            "material_text": "给定范围只描述已有配置，其他条件未知。",
        })
        identity, origin = goal["id"], goal["materials"][0]["id"]
        base = "/api/career/" + identity
        raw = post(base + "/materials", {"title": "合成未研究反例原文", "text": RAW})[
            "materials"][-1]["id"]
        for _ in range(8):
            inquiry = post(base + "/questions", {
                "question": OLD_QUESTION, "state": "parked", "next_evidence": "业务验收说明。",
                "hypothesis_a": "配置与复杂集成交付相同。",
                "hypothesis_b": "二者适用条件可能不同。",
                "source_passage": {"public_document_id": origin, "start": 0, "end": 10},
            })["questions"][-1]
            post(base + "/questions/" + inquiry["id"] + "/passages", {
                "passage": {"public_document_id": raw, "start": 0, "end": len(RAW)},
                "relation": "challenges", "user_note": ANNOTATION,
                "target_view": inquiry["hypothesis_a"],
            })
        for index in range(22):
            post(base + "/materials", {"title": f"合成其他资料{index}", "text": "无关说明。"})
        if remove_source:
            response = client.delete(base + "/materials/" + raw, headers=auth)
            assert response.status_code == 200, response.text
        before = deepcopy(client.get(base).json())
        assert not before["results"] and not model.contexts
        result = run_stage(client, identity, auth, "ask", inherit_focus=False,
                           question="合成调查笔记回查：证据校正时，先找回反例与原条件。")["results"][0]
        assert result["result"]["status"] == "completed", result["result"].get("stop_reason")
        recalled = result["result"]["career_learning_context"]["read_inquiries"][0]
        assert recalled["question"] == OLD_QUESTION and recalled["state"] == "parked"
        assert recalled["evidence_passages"][0]["in_current_scope"] is not remove_source
        assert result["result"]["model_calls"] == 5
        assert {row["public_document_id"] for row in result["result"]["evidence"]} == {
            origin if remove_source else raw,
        }
        assert result["question_id"] is None
        after = client.get(base).json()
        assert after["questions"] == before["questions"]
        assert after["materials"] == before["materials"]
        assert after["focus_question_id"] == before["focus_question_id"]
        assert not after["tasks"] and not after["insights"]
    with TestClient(app(), base_url="http://127.0.0.1") as client:
        restored = client.get(base).json()["results"][0]
        assert restored["result"]["career_learning_context"]["read_inquiries"] == [recalled]


def test_inquiry_notebook_is_goal_scoped_and_returns_independent_full_snapshots():
    project = {"career": {"questions": [{
        "id": "own", "question": OLD_QUESTION, "state": "parked", "created_at": "2026-11-01",
        "evidence_passages": [{"quote": RAW, "user_note": ANNOTATION}],
    }]}}
    before = deepcopy(project)
    notebook = LearningNotebook(lambda: project, None)
    assert notebook.search_inquiries(["证据校正"])["inquiries"][0]["id"] == "own"
    assert notebook.search_inquiries(["未记录的词"])["matching_count"] == 0
    with pytest.raises(ProbeError, match="INQUIRY_NOT_AVAILABLE"):
        notebook.read_inquiry("another-goal-question")
    with pytest.raises(ProbeError, match="INVALID_INQUIRY_OFFSET"):
        notebook.search_inquiries([], True)
    read = notebook.read_inquiry("own")["inquiry"]
    read["evidence_passages"][0]["user_note"] = "Changed only the returned copy."
    assert project == before
