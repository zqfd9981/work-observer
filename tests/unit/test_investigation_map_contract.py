"""Check the actual dynamically composed finish schema without calling a provider."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from work_observer.reports.cognition import ResearchWorkMap
from work_observer.research.agent import EXTRA_TOOLS, TOOLS, Claim
from work_observer.research.applications import tools as application_tools
from work_observer.research.cognition import VERSION, validate_map
from work_observer.research.investigation_maps import tools as map_tools
from work_observer.research.orchestration import (
    InvestigationBrief,
    execution_tools,
    planning_tool,
)


def test_map_contract_keeps_existing_task_and_application_outputs_and_resolves_refs():
    base = execution_tools(application_tools([*TOOLS, *EXTRA_TOOLS]))
    assert "plan_research" not in {row["name"] for row in base}
    assert "plan_investigation" in {row["name"] for row in base}
    original = deepcopy(base)
    invocation = map_tools(base, {"tasks": [{"output": "work_map"}]})
    finish = next(row for row in invocation if row["name"] == "finish_research")["parameters"]
    assert base == original
    assert {"claims", "gaps", "application_plan", "task_outcomes", "work_map"} <= set(
        finish["properties"],
    )
    assert "revisions" not in finish["properties"]
    assert "default" not in json.dumps(finish["properties"]["work_map"])
    Draft202012Validator.check_schema(finish)
    sample = {
        "claims": [], "gaps": ["缺少原文。"], "application_plan": None, "work_map": None,
        "task_outcomes": [{"task_index": 0, "status": "partial", "answer": "需要回读资料。",
                           "claim_indices": [], "questions": []}],
    }
    Draft202012Validator(finish).validate(sample)
    sample["claims"] = [{"category": category, "basis": "inference", "requirement": "unspecified",
                         "text": text, "evidence_ids": ["E1"]} for category, text in (
        ("task", "合成接口测试任务"), ("deliverable", "推导的测试记录"),
    )]
    sample["work_map"] = {
        "version": "work-map-v3-work-relations", "scope_note": "仅合成资料。",
        "work_types": [{"name": "接口检查", "problem": "定位异常", "tasks": "构造测试输入",
                        "deliverables": "测试记录", "claim_indices": [0, 1], "basis": "inference",
                        "boundary": "不是实际生产结果", "next_check": "补充实际约束"}],
        "work_relations": [{"source_claim_index": 0, "target_claim_index": 1,
                            "predicate": "produces", "basis": "inference",
                            "rationale": "由测试推导记录", "transfer_limit": "验收方式未知"}],
        "comparisons": [], "unknowns": ["企业准出权限未披露。"],
    }
    Draft202012Validator(finish).validate(sample)
    for property_name in ("work_map", "task_outcomes", "application_plan"):
        invalid = {key: value for key, value in sample.items() if key != property_name}
        assert list(Draft202012Validator(finish).iter_errors(invalid))


def test_planner_output_field_is_strict_and_replanning_cannot_drop_a_map_request():
    schema = planning_tool()["parameters"]
    assert "default" not in json.dumps(schema)
    plan = InvestigationBrief.model_validate({
        "objective": "解释工作关系", "missing_context": [],
        "tasks": [{"intent": "compare", "output": "work_map", "question": "任务和产出如何关联？",
                   "completion": "保留两侧依据。",
                   "queries": [{"terms": ["接口"], "reason": "任务词"}],
                   "retry_queries": [{"terms": ["测试"], "reason": "换一种表达"}]}],
    }).model_dump()
    Draft202012Validator(schema).validate(plan)
    assert plan["tasks"][0]["output"] == "work_map"
    # The existing task signature check runs before any repository or retrieval work.
    from work_observer.research.orchestration import investigate

    previous = deepcopy(plan)
    plan["tasks"][0]["output"] = "explanation"
    with pytest.raises(ValueError, match="输出形式"):
        investigate(None, plan, original_question="工作关系", scope={}, project_id=None,
                    as_of=None, aliases={}, previous=previous)


def test_cross_role_handoff_can_be_support_without_claiming_other_roles_output():
    evidence = {key: {"id": key, "job_id": job, "quote": quote} for key, job, quote in (
        ("E1", "role-a", "团队A维护数据接口，为下游团队提供输入。"),
        ("E2", "role-b", "团队B使用接口数据完成分析报告。"),
    )}
    claims = [Claim(category=kind, text=text, basis="direct", requirement="unspecified",
                    evidence_ids=[key]) for kind, text, key in (
        ("task", "团队A维护接口，为下游提供输入。", "E1"),
        ("deliverable", "团队B产出分析报告。", "E2"),
    )]
    value = {
        "version": VERSION, "scope_note": "两份不同岗位的合成资料。", "work_types": [],
        "work_relations": [{"source_claim_index": 0, "target_claim_index": 1,
                            "predicate": "supports", "basis": "inference",
                            "rationale": "由上下游提供和使用输入推导支撑联系。",
                            "transfer_limit": "不表示团队A产出了团队B的报告或拥有其准出权。"}],
        "comparisons": [], "unknowns": ["实际交接条件仍需核对。"],
    }
    answer = SimpleNamespace(work_map=ResearchWorkMap.model_validate(value), claims=claims)
    assert validate_map(answer, evidence)["work_relations"][0]["predicate"] == "supports"
    value["work_relations"][0]["predicate"] = "produces"
    answer.work_map = ResearchWorkMap.model_validate(value)
    with pytest.raises(ValueError, match="不同岗位"):
        validate_map(answer, evidence)
