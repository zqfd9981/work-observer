"""Bind suggested actions to questions, not just to the overall research run."""

from copy import deepcopy

import pytest

from work_observer.research.orchestration import outcomes


def design():
    investigation = {"tasks": [
        {"intent": "practice", "required_source_keys": ["first"]},
        {"intent": "practice", "required_source_keys": ["second"]},
    ]}
    evidence = {key: {"job_id": key} for key in ("first", "second")}
    plan = {"actions": [{"evidence_ids": ["first"]}, {"evidence_ids": ["second"]}]}
    values = [{"task_index": i, "status": "answered", "answer": "构造对照输入并记录差异。",
               "claim_indices": [], "action_indices": [i], "questions": []} for i in range(2)]
    return investigation, evidence, plan, values


def test_each_explicit_practice_request_needs_its_own_source_backed_design():
    investigation, evidence, plan, values = design()
    assert outcomes(values, investigation, [], evidence, application_plan=plan) == values
    missing = deepcopy(values)
    missing[1]["action_indices"] = []
    with pytest.raises(ValueError, match="可保存"):
        outcomes(missing, investigation, [], evidence, application_plan=plan)
    mixed = deepcopy(values)
    mixed[0]["action_indices"], mixed[1]["action_indices"] = [1], [0]
    with pytest.raises(ValueError, match="指定来源"):
        outcomes(mixed, investigation, [], evidence, application_plan=plan)
    for item in investigation["tasks"]:
        item.pop("required_source_keys")
    repeated = deepcopy(values)
    repeated[1]["action_indices"] = [0]
    with pytest.raises(ValueError, match="只能关联一个"):
        outcomes(repeated, investigation, [], evidence, application_plan=plan)


def test_design_missing_from_answer_stays_partial_and_cannot_be_marked_answered():
    investigation = {"tasks": [{"intent": "practice"}]}
    row = {"task_index": 0, "status": "partial", "answer": "资料不足，尚未设计可复现的检查。",
           "claim_indices": [], "questions": []}
    assert outcomes([row], investigation, [], {})[0]["action_indices"] == []
    with pytest.raises(ValueError, match="可保存"):
        outcomes([{**row, "status": "answered"}], investigation, [], {})


def test_action_indices_are_real_unique_integers_and_do_not_attach_to_interview():
    investigation, evidence, plan, values = design()
    for invalid in ([2], [-1], [0, 0], [True], ["0"]):
        attempt = deepcopy(values)
        attempt[0]["action_indices"] = invalid
        with pytest.raises(ValueError):
            outcomes(attempt, investigation, [], evidence, application_plan=plan)
    investigation["tasks"][0]["intent"] = "interview"
    with pytest.raises(ValueError, match="不能挂到其他问题"):
        outcomes(values, investigation, [], evidence, application_plan=plan)
