"""Observed false rejection: a denied merge must not become a required condition."""

import asyncio
from copy import deepcopy

import pytest
from test_feedback_requirement_negation import ExplanationModel
from test_review_feedback_repair import Model
from test_review_feedback_repair import workspace as workspace

from work_observer.config import Settings
from work_observer.research import agent, requirements, requirements_v2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("有相关经验者优先，不应并入必备要求。", []),
        ("Docker经验优先，不应将该项并入必备要求。", []),
        ("Docker经验优先，不应并入必备；Python必备。", ["必备"]),
        ("不应并入必备，但必须具备Java能力。", ["必须具备"]),
        ("不应只将Python并入必备。", ["必备"]),
        ("不能只并入必备，还需要其他技能。", ["必备"]),
        ("并入必备要求；Docker优先。", ["必备"]),
    ],
)
def test_denial_is_local_and_does_not_hide_positive_conditions(text, expected):
    assert requirements.required_markers(text, contextual_negation=True) == expected


def test_v2_keeps_its_original_observed_behavior():
    text = "Docker经验优先，不应并入必备要求。"
    assert requirements_v2.required_markers(text, contextual_negation=True) == ["必备"]
    assert requirements_v2.guard_contract()["sha256"] == (
        "2d9fcd8d4c50f3efec0661b5f01de2621534e1e90dbd50e687e56ea7b8910c8b"
    )
    assert requirements.required_markers(text, contextual_negation=True) == []
    assert (
        requirements.contract_for(requirements.PREVIOUS_GUARD) == requirements_v2.guard_contract()
    )


def test_new_guard_finishes_within_same_three_call_budget_without_retry(workspace):
    repo, _, job, _, original, _, _ = workspace
    text = "Docker经验优先，不应并入必备要求。"
    result = asyncio.run(
        agent.research(
            repo,
            original["question"],
            Settings(),
            job_ids=[job],
            max_calls=3,
            allow_proposals=False,
            model=ExplanationModel(text),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 3
    assert result["claims"][0]["text"] == text
    assert result["qualification_validation"]["version"] == requirements.CURRENT_GUARD
    assert not any(row.get("validation") for row in result["trace"])


def test_real_required_clause_still_requires_a_separate_claim(workspace):
    repo, _, job, _, original, _, _ = workspace
    result = asyncio.run(
        agent.research(
            repo,
            original["question"],
            Settings(),
            job_ids=[job],
            max_calls=4,
            allow_proposals=False,
            model=ExplanationModel("Docker经验优先，不应并入必备；Python必备。"),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 4
    assert [row["requirement"] for row in result["claims"]] == ["preferred", "required"]


def test_interrupted_v2_uses_original_hash_rules_and_remaining_budget(workspace):
    repo, store, job, _, original, _, _ = workspace
    contract = requirements_v2.guard_contract()
    params = dict(
        question=original["question"],
        job_ids=[job],
        max_calls=5,
        timeout=180,
        allow_public=False,
        allow_proposals=False,
        approach="standard",
        qualification_validation=contract,
    )
    run = store.create(params)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            agent._research(
                repo,
                original["question"],
                Settings(),
                job_ids=[job],
                max_calls=5,
                checkpoint=(store, run["id"]),
                allow_proposals=False,
                model=Model(cancel=True),
                _qualification_guard=requirements.PREVIOUS_GUARD,
            )
        )
    store.save(run["id"], state="interrupted")
    before = deepcopy(store.load_checkpoint(run["id"]))
    assert before["result"]["model_calls"] == 3
    result = asyncio.run(
        agent.research(
            repo,
            original["question"],
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=ExplanationModel("Docker经验优先，不应并入必备要求。"),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 5
    assert result["qualification_validation"] == contract
    assert result["research_method_sha256"] == before["result"]["research_method_sha256"]
    assert store.get(run["id"])["input"] == params
    assert store.load_checkpoint(run["id"])["max_calls"] == 5
    assert any(row.get("validation") == "citation_or_coverage_rejected" for row in result["trace"])
