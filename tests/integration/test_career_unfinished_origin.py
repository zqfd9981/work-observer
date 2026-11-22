"""A narrower inquiry resumes from actual source locators, without adopting a failed draft."""

import json
import re

import pytest
from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade


class UnfinishedOriginModel(ModelClient):
    def __init__(self):
        self.contexts, self.last_usage, self.origin = [], {}, None

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        inquiry = context["project_context"]["career_evidence"]["selected_inquiry"]
        outputs = [json.loads(row["output"]) for row in history
                   if row.get("type") == "function_call_output"]
        if self.origin is not None:
            assert inquiry["origin_discussion"] is None
            origin = inquiry["incomplete_origin"]
            assert origin["step_id"] == self.origin["step_id"]
            assert origin["question"] == self.origin["user_question"]
            assert origin["status"] != "completed"
            assert origin["source_cutoff"] == self.origin["result"]["created_at"]
            assert len(origin["source_references_to_reread"]) == 2
            assert "UNADOPTED_FAILED_DRAFT" not in json.dumps(inquiry)
            assert "work_map" not in origin and "claim_details_to_recheck" not in origin
            assert all("quote" not in row for row in origin["source_references_to_reread"])
            assert "未完成草稿" in inquiry["origin_notice"]
            assert "incomplete_origin" in context["question"]
        if not outputs:
            documents = context["fixed_scope"]["archived_public_ids"]
            assert len(documents) == 2
            name, args = "read_archived_documents", {
                "reads": [{"document_id": identity, "start": 0} for identity in documents]
            }
        elif self.origin is None:
            if len(outputs) > 1:
                raise ProbeError("SYNTHETIC_MODEL_STOP")
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "inference",
                            "requirement": "unspecified", "text": "UNADOPTED_FAILED_DRAFT",
                            "evidence_ids": ["never-read"]}],
                "gaps": ["UNADOPTED_GAP_NOT_A_NEW_QUESTION"],
            }
        else:
            evidence = outputs[0]["evidence"]
            assert len(evidence) == 2
            name, args = "finish_research", {
                "claims": [{"category": "task", "basis": "synthesis",
                            "requirement": "unspecified",
                            "text": "两份合成记录的交付物不同；实际并发和验收权限仍需核实。",
                            "evidence_ids": [row["id"] for row in evidence]}],
                "gaps": ["实际并发条件与验收人仍未知。"],
            }
        call = {"type": "function_call", "name": name, "arguments": json.dumps(args),
                "call_id": str(len(history))}
        return [call], call


@pytest.mark.parametrize("source_kind", ["failed", "evidence_only"])
def test_unfinished_origin_is_reread_as_sources_after_reopen(tmp_path, source_kind):
    database = tmp_path / "unfinished-origin.db"
    upgrade(database)
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    model = UnfinishedOriginModel()

    def app():
        return create_app(settings, model=model, reports_dir=tmp_path / "reports")

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}

        def save(path, values):
            response = client.post(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        goal = save("/api/career", {"title": "合成未完成研究继续调查",
                    "goal": "保留来源，缩小问题", "first_question": "两份记录能解释什么工作？"})
        identity, parent_id = goal["id"], goal["focus_question_id"]
        base = "/api/career/" + identity
        ids = []
        for index, text in enumerate([
            "合成甲记录交付差异清单；实际验收人未说明。",
            "合成乙记录交付运行日志；并发条件未观察。",
        ]):
            ids.append(save(base + "/materials", {"title": "合成未完成起点" + str(index),
                                                  "text": text})["materials"][-1]["id"])
        stopped = run_stage(client, identity, auth, "ask", question_id=parent_id,
                            material_ids=ids, question="合成先广读后停下",
                            offline=source_kind == "evidence_only")
        source = stopped["results"][0]
        assert source["result"]["status"] != "completed"
        assert len(source["result"]["evidence"]) == 2
        assert not source["result"]["claims"]
        if source_kind == "failed":
            assert source["state"] == "failed"
            assert "UNADOPTED_FAILED_DRAFT" in json.dumps(source["result"]["submission_feedback"])
        else:
            assert source["result"]["status"] == "evidence_only"
            assert not source["result"]["model_calls"]
        calls_before = stopped["usage"]["calls"]
        saved = save(base + "/questions", {"question": "两份记录分别交付什么，哪些仍未知？",
                     "source_step_id": source["step_id"], "parent_question_id": parent_id,
                     "material_ids": ids})
        child = saved["questions"][-1]
        assert saved["usage"] == stopped["usage"]
        model.origin = source

    with TestClient(app(), base_url="http://127.0.0.1") as client:
        auth = {"X-WO-Token": re.search(
            r'name="wo-token" content="([^"]+)"', client.get("/").text,
        )[1]}
        continued = run_stage(client, identity, auth, "ask", question_id=child["id"],
                              material_ids=ids, question=child["question"])
        answer = continued["results"][0]
        assert answer["result"]["status"] == "completed", answer["result"]
        assert answer["source_step_id"] is None and answer["question_id"] == child["id"]
        assert {row["public_document_id"] for row in answer["result"]["evidence"]} == set(ids)
        assert continued["usage"]["calls"] - calls_before == 2
        assert next(row for row in continued["results"] if row["step_id"] == source["step_id"])[
            "result"
        ] == source["result"]
        assert next(row for row in continued["questions"] if row["id"] == child["id"])[
            "conclusion"
        ] == ""
        assert all(row["state"] == "open" for row in continued["questions"])
