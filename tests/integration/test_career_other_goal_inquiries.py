"""Unfinished inquiries can be recalled, then continued from the exact input snapshot."""

import json
import re

from starlette.testclient import TestClient
from test_career_workspace import run_stage

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import ModelClient
from work_observer.storage.database import upgrade

MARKER = "合成跨岗问题接力"
QUESTION = "同名工具是否意味着相同的任务、交付与责任？"
HYPOTHESIS_A = "工具相同，分工可能相同；仍待原场景核实。" * 12
HYPOTHESIS_B = "业务对象和验收条件不同，分工可能不同；不能直接外推。" * 10
SOURCE = (
    "合成旧场景🤔\r\n工具用于记录不同业务对象；个人验收权限未说明。\r\n"
    "限定：工具名称不足以确定相同职责。"
)
NOTE = "先核对业务对象、个人分工与验收边界。" * 26 + "末尾：" + MARKER


class OtherGoalInquiryModel(ModelClient):
    def __init__(self):
        self.last_usage, self.contexts = {}, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        project = context["project_context"]
        inquiry = project["career_evidence"].get("selected_inquiry") or {}
        carried = (inquiry.get("carried_understanding") or {}).get("inquiry")
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        current = next(
            row["id"]
            for row in context["fixed_scope"]["public_document_titles"]
            if row["title"] == "合成当前场景原文"
        )
        if carried:
            assert carried["hypothesis_a"] == HYPOTHESIS_A
            assert carried["hypothesis_b"] == HYPOTHESIS_B
            assert carried["evidence_passages"][0]["user_note"] == NOTE
            assert inquiry["state"] == "open" and not inquiry["conclusion"]
            assert not inquiry["hypothesis_a"] and not inquiry["hypothesis_b"]
            assert carried["material_ids"][0] not in context["fixed_scope"]["archived_public_ids"]
        if carried and not outputs:
            name, args = "read_archived_document", {"document_id": current, "start": 0}
        elif not carried and not outputs:
            name, args = "search_other_goal_memory", {"terms": [MARKER], "offset": 0}
        elif not carried and len(outputs) == 1:
            found = outputs[0]["memories"]
            assert outputs[0]["matching_count"] == len(found) == 1
            assert found[0]["kind"] == "inquiry" and found[0]["preview"]["state"] == "parked"
            assert any(
                field.startswith("passage_") for field in found[0]["preview"]["matched_fields"]
            )
            name, args = (
                "read_other_goal_memory",
                {key: found[0][key] for key in ("project_id", "kind", "record_id")},
            )
        elif not carried and len(outputs) == 2:
            record = outputs[-1]["memory"]
            assert record["question"] == QUESTION and record["hypothesis_a"] == HYPOTHESIS_A
            assert record["hypothesis_b"] == HYPOTHESIS_B and record["state"] == "parked"
            passage = record["evidence_passages"][0]
            assert passage["quote"] == SOURCE and passage["start"] == 0
            assert passage["target_view"] == HYPOTHESIS_A and passage["user_note"] == NOTE
            assert not passage["in_current_scope"] and "evidence" not in outputs[-1]
            name, args = "read_archived_document", {"document_id": current, "start": 0}
        else:
            evidence = outputs[-1]["evidence"]
            assert {row["public_document_id"] for row in evidence} == {current}
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "inference",
                            "requirement": "unspecified",
                            "text": "旧问题与标注只供提出查证方向；"
                            "当前对象和权限需单独核对，不能从标注关系推定解释已成立或已证伪。",
                            "evidence_ids": [row["id"] for row in evidence],
                        }
                    ],
                    "gaps": ["旧原文未在当前范围内重读，实际分工和验收仍未知。"],
                },
            )
            if project.get("previous_findings") or project.get("historical_reply"):
                args["revisions"] = []
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_unfinished_other_goal_inquiry_continues_with_full_read_snapshot_and_current_scope(
    tmp_path,
):
    database = tmp_path / "other-goal-inquiry.db"
    upgrade(database)
    model = OtherGoalInquiryModel()
    settings = Settings(database_path=database, raw_directory=tmp_path / "raw")
    with TestClient(
        create_app(settings, model=model, reports_dir=tmp_path / "reports"),
        base_url="http://127.0.0.1",
    ) as client:
        auth = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }

        def save(path, values, method="post"):
            response = getattr(client, method)(path, headers=auth, json=values)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        source = save(
            "/api/career",
            {
                "title": "合成未完调查来源",
                "goal": "保留竞争解释与原文标注",
                "material_title": "合成旧场景原文",
                "material_text": SOURCE,
            },
        )
        base = "/api/career/" + source["id"]
        original = {
            "question": QUESTION,
            "hypothesis_a": HYPOTHESIS_A,
            "hypothesis_b": HYPOTHESIS_B,
            "state": "parked",
            "conclusion": "暂存理解，仍待核实。",
            "material_ids": [source["materials"][0]["id"]],
            "next_evidence": "需要实际分工资料。",
        }
        question = save(base + "/questions", original)["questions"][-1]
        save(
            base + "/questions/" + question["id"] + "/passages",
            {
                "passage": {
                    "public_document_id": source["materials"][0]["id"],
                    "start": 0,
                    "end": len(SOURCE),
                },
                "relation": "challenges",
                "target_view": HYPOTHESIS_A,
                "user_note": NOTE,
            },
        )
        before_source = client.get(base).json()
        assert not before_source["results"]
        target = save(
            "/api/career",
            {
                "title": "合成当前问题接力",
                "goal": "核对新对象下的适用性",
                "first_question": "新场景怎样核对分工？",
                "material_title": "合成当前场景原文",
                "material_text": "当前场景的工作对象不同，个人验收权限未明确。",
            },
        )
        target_base = "/api/career/" + target["id"]
        first = run_stage(
            client,
            target["id"],
            auth,
            "ask",
            question="合成跨目标问题接力：" + MARKER,
            question_id=target["questions"][0]["id"],
        )["results"][0]
        assert first["result"]["status"] == "completed", first["result"]["stop_reason"]
        assert first["result"]["model_calls"] == 4
        assert client.get(base).json() == before_source
        save(
            base + "/questions/" + question["id"],
            {
                **original,
                "hypothesis_a": "来源后来编辑的新猜想。",
                "conclusion": "来源后来补充的理解。",
            },
            "patch",
        )
        source_after_edit = client.get(base).json()
        before_import = client.get(target_base).json()
        values = {
            "source_project_id": source["id"],
            "kind": "question",
            "record_id": question["id"],
            "source_step_id": first["step_id"],
        }
        invalid = client.post(
            target_base + "/reuse", headers=auth, json={**values, "source_step_id": "0" * 32}
        )
        assert invalid.status_code == 422
        assert client.get(target_base).json() == before_import
        copied_data = save(target_base + "/reuse", values)
        copied = copied_data["questions"][-1]
        snapshot = copied["carried_understanding"]["inquiry"]
        assert snapshot["hypothesis_a"] == HYPOTHESIS_A and snapshot["hypothesis_b"] == HYPOTHESIS_B
        assert snapshot["evidence_passages"][0]["user_note"] == NOTE
        assert snapshot["evidence_passages"][0]["quote"] == SOURCE
        assert copied["state"] == "open" and not copied["conclusion"]
        assert not copied["hypothesis_a"] and not copied["hypothesis_b"]
        assert not copied["material_ids"] and not copied["selected_job_ids"]
        assert copied["source_step_id"] == first["step_id"]
        assert copied_data["document_ids"] == target["document_ids"]
        assert copied_data["results"] == before_import["results"]
        assert copied_data["usage"] == before_import["usage"]
        assert save(target_base + "/reuse", values) == copied_data
        assert client.get(base).json() == source_after_edit
        second = run_stage(
            client,
            target["id"],
            auth,
            "ask",
            question="按当前对象继续核对旧问题。",
            question_id=copied["id"],
        )["results"][0]
        assert second["result"]["status"] == "completed", second["result"]["stop_reason"]
        assert second["result"]["model_calls"] == 2
        assert client.get(base).json() == source_after_edit
        erased = client.delete("/api/projects/" + source["id"], headers=auth)
        assert erased.status_code == 200, erased.text
        assert target["id"] in erased.json()["affected_project_ids"]
        assert not client.get("/api/projects/" + target["id"]).json().get("career")
