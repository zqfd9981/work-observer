"""Scripted routing into the existing map model; no real intent/semantic evaluation."""

import json
import time

import pytest
from starlette.testclient import TestClient
from test_adaptive_investigation import ScriptedPlanner, brief, prepare, settled, task, workspace

from work_observer.reports.cognition import checked_map
from work_observer.research.cognition import VERSION


class MappedPlanner(ScriptedPlanner):
    def __init__(self, plan, *, bad_once=None, **kwargs):
        super().__init__(plan, **kwargs)
        self.bad_once = bad_once
        self.finish_schemas = []
        self.feedback = []

    async def turn(self, history):
        self.feedback.extend(json.loads(row["output"])["work_map_error"] for row in history
                             if row.get("type") == "function_call_output"
                             and "work_map_error" in json.loads(row["output"]))
        outputs, call = await super().turn(history)
        if call["name"] != "finish_research":
            return outputs, call
        finish = next(row for row in self.tools if row["name"] == "finish_research")
        self.finish_schemas.append(finish["parameters"])
        if "work_map" not in finish["parameters"]["properties"]:
            return outputs, call
        argument = json.loads(call["arguments"])
        plans = [json.loads(row["output"]) for row in history
                 if row.get("type") == "function_call_output"
                 and json.loads(row["output"]).get("engine") == "langgraph"]
        evidence = plans[-1]["evidence"]
        claims, relations = [], []
        for item in evidence:
            index = len(claims)
            claims.extend([
                {"category": "task", "basis": "direct", "requirement": "unspecified",
                 "text": "负责接口开发与测试。", "evidence_ids": [item["citation_key"]]},
                {"category": "deliverable", "basis": "inference", "requirement": "unspecified",
                 "text": "据测试任务推导可记录输入与结果，原文未明确列出验收产物。",
                 "evidence_ids": [item["citation_key"]]},
            ])
            relations.append({
                "source_claim_index": index, "target_claim_index": index + 1,
                "predicate": "produces", "basis": "inference",
                "rationale": "由测试任务推导可保留输入与结果记录。",
                "transfer_limit": "这是推导，不证明实际执行、企业验收或个人准出权限。",
            })
        value = {
            "version": VERSION, "scope_note": "仅对照两份合成JD，关系仍需核对。",
            "work_types": [], "work_relations": relations,
            "comparisons": [{
                "relation_indices": [0, 1], "common_ground": "都提到接口测试任务。",
                "differences": "具体业务条件和验收差异尚未披露。",
                "transfer_conditions": "需先核对输入、业务约束与责任分工。",
                "basis": "inference", "unknowns": ["可迁移性未实际验证。"],
            }] if len(relations) > 1 else [],
            "unknowns": ["最终准出权限未披露。"],
        } if evidence else None
        argument["claims"] = claims
        for index, outcome in enumerate(argument["task_outcomes"]):
            outcome["claim_indices"] = list(range(len(claims))) if index == 0 else [0]
        argument["work_map"] = value
        if self.bad_once == "null":
            argument["work_map"] = None
        elif self.bad_once == "dangling" and value:
            value["work_relations"][0]["target_claim_index"] = 23
        elif self.bad_once == "one_side" and value:
            value["work_relations"] = value["work_relations"][:1]
            value["comparisons"] = []
        elif self.bad_once == "cross_roles" and value:
            value["work_relations"][0]["target_claim_index"] = 3
            value["work_relations"][1]["target_claim_index"] = 1
        self.bad_once = None
        call["arguments"] = json.dumps(argument)
        return outputs, call


def mapped_task(*, empty=False):
    return {**task("compare", terms=["接口"] if not empty else ["不存在的主题"],
                  retry=["测试"] if not empty else ["仍不存在的主题"]), "output": "work_map"}


@pytest.mark.parametrize("bad_once", [None, "null", "dangling", "one_side", "cross_roles"])
def test_natural_map_request_preserves_two_sides_and_compound_practice(tmp_path, bad_once):
    model = MappedPlanner(brief([mapped_task(), task("practice")]),
                          bad_once=bad_once, produce_plan=True)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, jobs = prepare(
            client, "把两份JD的任务和产出关系画清楚，再给一个验证",
        )
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        data = settled(client, base)
        result = data["results"][0]["result"]
        assert result["status"] == "completed", result
        work_map = checked_map(result)
        assert len(work_map["work_relations"]) == 2
        assert work_map["comparisons"][0]["claim_indices"] == [0, 1, 2, 3]
        assert {row["job_id"] for row in result["evidence"]} == set(jobs)
        assert result["investigation"]["tasks"][0]["output"] == "work_map"
        assert result["application_plan"]["purpose"] == "understanding_check"
        assert not data["tasks"] and not data["insights"]
        assert all("revisions" not in schema["properties"] for schema in model.finish_schemas)
        assert result["model_calls"] == (3 if bad_once else 2)
        if bad_once:
            assert result["trace"][1]["validation"] == "citation_or_coverage_rejected"
        if bad_once == "cross_roles":
            assert any("不同岗位" in message for message in model.feedback)
        first = work_map["work_relations"][0]
        assert first["source_text"] == result["claims"][first["source_claim_index"]]["text"]
        assert "不证明实际执行" in first["transfer_limit"]
        saved = client.get("/api/career/work-relations", params={"goal_id": goal})
        assert saved.status_code == 200, saved.text
        assert saved.json()["total_count"] == 2
        assert all(row["step_id"] == step for row in saved.json()["relations"])


def test_missing_originals_can_return_partial_answer_without_a_fabricated_map(tmp_path):
    model = MappedPlanner(brief([mapped_task(empty=True)]))
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "没找到的那项工作能画出关系吗？")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert not result.get("work_map") and not result["claims"]
        assert result["investigation"]["outcomes"][0]["status"] == "partial"


def test_plain_question_does_not_receive_map_or_revision_fields(tmp_path):
    model = MappedPlanner(brief([mapped_task()]))
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "先把工作关系画出来")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        original = settled(client, base)["results"][0]["result"]
        assert original["work_map"]
        model.plan = brief()
        prepared = client.post(base + "/prepare", headers=auth, json={
            "kind": "ask", "question": "这次只回答一句具体任务", "source_step_id": step,
            "adaptive": True,
        })
        assert prepared.status_code == 201, prepared.text
        client.post(f"/api/projects/{goal}/run", headers=auth,
                    json={"step_id": prepared.json()["step_id"]})
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert "work_map" not in model.finish_schemas[-1]["properties"]
        assert "revisions" not in model.finish_schemas[-1]["properties"]
        assert not result.get("work_map")


def test_map_contract_is_restored_after_pausing_the_same_question(tmp_path):
    model = MappedPlanner(brief([mapped_task()]), pause=True)
    with TestClient(workspace(tmp_path, model), base_url="http://127.0.0.1") as client:
        auth, goal, base, step, _ = prepare(client, "把这两份工作的任务产出关系对照起来")
        client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        for _ in range(300):
            row = client.get(base).json()["results"][0]
            if (row.get("result") or {}).get("investigation"):
                break
            time.sleep(0.01)
        assert row["result"]["investigation"]["tasks"][0]["output"] == "work_map"
        client.post(f"/api/projects/{goal}/pause", headers=auth, json={})
        assert settled(client, base)["results"][0]["state"] == "interrupted"
        model.pause = False
        response = client.post(f"/api/projects/{goal}/run", headers=auth, json={"step_id": step})
        assert response.status_code == 202, response.text
        result = settled(client, base)["results"][0]["result"]
        assert result["status"] == "completed", result
        assert checked_map(result)["work_relations"]
        assert sum(row["tool"] == "plan_investigation" for row in result["trace"]) == 1
