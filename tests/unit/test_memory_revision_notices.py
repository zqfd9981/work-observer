"""Source-specific notices do not overwrite adoption or create dependency cycles."""

from copy import deepcopy

import pytest
from test_dependency_eligibility import dependencies as dependencies
from test_dependency_eligibility import source

from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.research.projects import ProjectService
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.unified import UnifiedRetrieval


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


@pytest.mark.parametrize("uses_other_job", [False, True])
def test_recalled_revision_uses_its_own_support_scope_not_every_source_read_in_that_run(
    dependencies,
    uses_other_job,
):
    repo, store, memory, jobs, _ = dependencies
    _, saved, second = case(dependencies)
    extra = Catalog(repo).evidence(jobs[1])
    second["evidence"].extend(extra)
    second["scope"] = Catalog(repo).query(job_ids=jobs)
    revision = second["cognition_revisions"][0]
    revision["new_claim_indices"] = [0]
    if uses_other_job:
        # Even a source used only by the referenced new statement belongs to its scope.
        second["claims"][0]["evidence_ids"].append(extra[0]["id"])
    store.save(second["run_id"], state="finished", result=second)
    assert memory.derived_eligibility(second["run_id"])["eligible"]
    recalled = memory.recall("RAG", jobs[:1])[0]
    notice = recalled["revision_notices"][0]
    assert bool(notice.get("scope_limited")) == uses_other_job
    assert bool(notice["new_statements"]) == (not uses_other_job)
    found = UnifiedRetrieval(repo).search(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert found["knowledge"][0]["id"] == saved["id"]
    assert bool(found["knowledge"][0]["revision_notices"][0].get("scope_limited")) == uses_other_job
    assert memory.list()[0]["status"] == "active"


def test_unified_selected_archives_scope_the_new_statement_in_a_revision(dependencies, tmp_path):
    from work_observer.connectors.public_documents import PublicDocumentService
    from work_observer.research.archived_sources import read

    repo, store, memory, jobs, _ = dependencies
    _, saved, second = case(dependencies)
    document = PublicDocumentService(repo, tmp_path / "materials").archive_text(
        "合成分工说明",
        "RAG任务与最终决策的分工说明。",
    )["document"]
    extra = read(repo, document["id"], 0, [document["id"]])["evidence"]
    second["evidence"].extend(extra)
    second["scope"]["archived_public_ids"] = [document["id"]]
    second["claims"][0]["evidence_ids"].append(extra[0]["id"])
    second["cognition_revisions"][0]["new_claim_indices"] = [0]
    second["cognition_revisions"][0]["reason"] = "PRIVATE_OUTSIDE_SELECTED_MATERIAL"
    store.save(second["run_id"], state="finished", result=second)
    assert memory.derived_eligibility(second["run_id"])["eligible"]
    narrow = UnifiedRetrieval(repo).search(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert narrow["knowledge"][0]["id"] == saved["id"]
    notice = narrow["knowledge"][0]["revision_notices"][0]
    assert notice["scope_limited"] and not notice["new_statements"]
    assert not notice["evidence_ids"]
    assert "PRIVATE_OUTSIDE_SELECTED_MATERIAL" not in str(notice)
    broad = UnifiedRetrieval(repo).search(
        ["RAG"], job_ids=jobs[:1], public_document_ids=[document["id"]]
    )
    assert broad["knowledge"][0]["revision_notices"][0]["run_id"] == second["run_id"]


def test_unified_budgets_revision_text_and_reports_omitted_knowledge_without_truncating_it(
    dependencies,
):
    repo, store, memory, jobs, _ = dependencies
    _, saved, second = case(dependencies)
    revision = second["cognition_revisions"][0]
    revision.update(new_claim_indices=[0], trigger="recheck")
    revision["reason"] = "核对具体任务与责任范围；" * 50
    text = "RAG任务和权限仍需按原文核实；" * 60
    second["claims"][0]["text"] = text
    revision["new_statements"] = [text]
    revision["aspects"] = [
        dict(
            previous_excerpt=revision["previous_statement"],
            decision="revise",
            new_claim_indices=[0],
            new_statements=[text],
            reason="逐项说明不能由任务推出权限；" * 50,
            evidence_ids=revision["evidence_ids"],
        )
    ]
    store.save(second["run_id"], state="finished", result=second)
    found = UnifiedRetrieval(repo).search(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert found["context_characters"] <= found["context_limit"]
    assert not found["knowledge"] and found["evidence"]
    assert found["knowledge_omissions"] == [
        dict(
            id=saved["id"],
            reason="context_limit",
            has_revision_notices=True,
        )
    ]
    assert memory.revision_notices(saved["id"])[0]["aspects"][0]["new_statements"] == [text]
    assert memory.list()[0]["status"] == "active"
