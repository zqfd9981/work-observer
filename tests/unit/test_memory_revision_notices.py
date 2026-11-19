"""Source-specific notices do not overwrite adoption or create dependency cycles."""

from copy import deepcopy

import pytest
from test_dependency_eligibility import dependencies as dependencies
from test_dependency_eligibility import source

from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.research.projects import ProjectService


def case(workspace, *, project_id=None, decision="revise"):
    repo, store, memory, jobs, _ = workspace
    first = source(repo, store, jobs[:1], project_id=project_id)
    saved = memory.create(
        "knowledge",
        first["claims"][0]["text"],
        evidence=first["evidence"],
        source_run_id=first["run_id"],
        origin="agent",
    )
    saved = memory.activate(saved["id"])
    second = source(repo, store, jobs[:1], memories=[saved], project_id=project_id)
    second["claims"][0]["text"] = "RAG 任务不等于个人独立交付权限。"
    second["cognition_revisions"] = [
        {
            "previous_run_id": first["run_id"],
            "previous_claim_index": 0,
            "previous_statement": first["claims"][0]["text"],
            "decision": decision,
            "reason": "重读后的权限边界需核对。",
            "new_statements": [second["claims"][0]["text"]],
            "evidence_ids": [second["evidence"][0]["id"]],
        }
    ]
    store.save(second["run_id"], state="finished", result=second)
    return first, saved, second


@pytest.mark.parametrize("decision", ["revise", "withdraw", "unresolved", "retain"])
def test_notices_flow_to_recall_without_mutating_history_or_status(dependencies, decision):
    repo, store, memory, jobs, _ = dependencies
    first, saved, second = case(dependencies, decision=decision)
    original = deepcopy(store.get(first["run_id"]))
    validity = memory.validity(saved["id"])
    assert validity["eligible"]
    assert bool(validity["revision_notices"]) == (decision != "retain")
    recalled = memory.recall("RAG", jobs[:1])[0]
    assert recalled["status"] == "active" and recalled["content"] == saved["content"]
    assert bool(recalled.get("revision_notices")) == (decision != "retain")
    if decision != "retain":
        assert recalled["revision_notices"][0]["run_id"] == second["run_id"]
    # The new run used this memory itself: notices must not recurse into eligibility.
    assert memory.derived_eligibility(second["run_id"])["eligible"]
    assert store.get(first["run_id"]) == original
    assert memory.list()[0] == saved


def test_exact_claim_time_and_excluded_run_boundaries(dependencies):
    _, store, memory, jobs, _ = dependencies
    _, saved, second = case(dependencies)
    before = "2000-01-01T00:00:00+00:00"
    assert memory.revision_notices(saved["id"], at=before) == []
    assert (
        "revision_notices"
        not in memory.recall("RAG", jobs[:1], excluded_runs=[second["run_id"]])[0]
    )
    for field, value in (("previous_claim_index", 1), ("previous_statement", "无关判断")):
        modified = deepcopy(second)
        modified["cognition_revisions"][0][field] = value
        store.save(second["run_id"], result=modified)
        assert memory.revision_notices(saved["id"]) == []
    store.save(second["run_id"], state="invalidated", result=second)
    assert memory.revision_notices(saved["id"]) == []


def test_project_notice_does_not_leak_into_other_project(dependencies):
    _, store, memory, jobs, _ = dependencies
    project = ProjectService(store).create("合成研究", "RAG", jobs[:1])
    _, saved, _ = case(dependencies, project_id=project["id"])
    assert memory.revision_notices(saved["id"])
    assert memory.recall("RAG", jobs[:1], project_id=project["id"])[0]["revision_notices"]
    assert "revision_notices" not in memory.recall("RAG", jobs[:1], project_id="b" * 32)[0]


def test_rejected_revision_is_not_a_notice(dependencies):
    repo, store, memory, _, _ = dependencies
    _, saved, second = case(dependencies)
    review = QualityReviewService(store, repo)
    packet = review.packet(second["run_id"])
    review.submit(
        second["run_id"],
        {
            "result_sha256": packet["result_sha256"],
            "decision": "reject",
            "reviewer": "合成复核",
            "reviewer_kind": "agent_assisted",
            "note": "合成否决",
            "dimensions": {key: {"rating": "fail", "reason": "合成否决"} for key in DIMENSIONS},
            "claim_reviews": [
                {
                    "index": 0,
                    "support": "unsupported",
                    "requirement": "correct",
                    "note": "合成否决",
                }
            ],
        },
    )
    assert memory.revision_notices(saved["id"]) == []
