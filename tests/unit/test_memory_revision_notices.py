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


def case(workspace, *, project_id=None, decision="revise", uses_memory=True):
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
    second = source(
        repo, store, jobs[:1], memories=[saved] if uses_memory else [], project_id=project_id
    )
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


def test_later_retention_is_recalled_with_earlier_challenge_without_deciding_truth(dependencies):
    repo, store, memory, jobs, _ = dependencies
    original, saved, challenged = case(dependencies)
    before = deepcopy(store.get(original["run_id"]))
    retained = source(repo, store, jobs[:1], continued_from=[challenged["run_id"]])
    retained["cognition_revisions"] = [
        dict(
            previous_run_id=original["run_id"],
            previous_claim_index=0,
            previous_statement=original["claims"][0]["text"],
            decision="retain",
            trigger="recheck",
            new_claim_indices=[0],
            new_statements=[retained["claims"][0]["text"]],
            evidence_ids=retained["claims"][0]["evidence_ids"],
            reason="后续重新核对任务范围，保留原任务判断；不推出个人上线权。",
        )
    ]
    store.save(retained["run_id"], state="finished", result=retained)
    recalled = memory.recall("RAG", jobs[:1])[0]
    notices = recalled["revision_notices"]
    assert [row["run_id"] for row in notices] == [retained["run_id"], challenged["run_id"]]
    assert notices[0]["decision"] == "retain" and "曾有" in notices[0]["notice"]
    retrieved = UnifiedRetrieval(repo).search(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert [row["run_id"] for row in retrieved["knowledge"][0]["revision_notices"]] == [
        retained["run_id"],
        challenged["run_id"],
    ]
    assert memory.validity(saved["id"])["eligible"]
    assert memory.list()[0] == saved and store.get(original["run_id"]) == before
    store.save(retained["run_id"], state="invalidated")
    assert (
        memory.recall("RAG", jobs[:1])[0]["revision_notices"][0]["run_id"] == challenged["run_id"]
    )


def test_rewritten_memory_keeps_source_claim_leads_with_an_explicit_historical_match(dependencies):
    repo, store, memory, jobs, _ = dependencies
    original, saved, later = case(dependencies, uses_memory=False)
    before = deepcopy(store.get(original["run_id"]))
    revised = memory.activate(memory.revise(saved["id"], "合成 RAG 评估任务，个人权限待核实")["id"])
    revised = memory.activate(
        memory.revise(revised["id"], "合成 RAG 评估工作，仅保留已披露任务")["id"]
    )
    assert memory.derived_eligibility(later["run_id"])["eligible"]
    recalled = memory.recall("RAG", jobs[:1])[0]
    assert recalled["id"] == revised["id"] and recalled["content"] == revised["content"]
    notice = recalled["revision_notices"][0]
    assert notice["run_id"] == later["run_id"]
    assert notice["previous_statement"] == saved["content"]
    assert notice["memory_match"] == {"id": saved["id"], "version": 1}
    assert "当前表述已经改写" in notice["memory_match_note"]
    assert "是否仍受影响" in notice["memory_match_note"]
    retrieved = UnifiedRetrieval(repo).search(["RAG"], job_ids=jobs[:1], public_document_ids=[])
    assert (
        retrieved["knowledge"][0]["revision_notices"][0]["memory_match"] == notice["memory_match"]
    )
    assert memory.list()[0] == revised
    assert store.get(original["run_id"]) == before
    assert memory.recall("RAG", jobs[:1], excluded_runs=[later["run_id"]]) == [revised]


def test_exact_current_claim_match_wins_over_old_version_and_unbound_notes_stay_unbound(
    dependencies,
):
    _, store, memory, jobs, _ = dependencies
    original, saved, _ = case(dependencies, uses_memory=False)
    original["claims"].append({**original["claims"][0], "text": "合成 RAG Python 开发任务"})
    store.save(original["run_id"], result=original)
    revised = memory.activate(memory.revise(saved["id"], original["claims"][1]["text"])["id"])
    # The old correction targets claim 0, not the explicitly selected claim 1.
    assert memory.recall("RAG", jobs[:1]) == [revised]
    unbound = memory.create(
        "knowledge",
        "合成 RAG 汇总，未绑定某条原判断",
        source_run_id=original["run_id"],
        evidence=original["evidence"],
        origin="agent",
    )
    unbound = memory.activate(unbound["id"])
    rewritten = memory.activate(
        memory.revise(unbound["id"], "合成 RAG 汇总，仍是未绑定的改写")["id"]
    )
    assert not memory.validity(rewritten["id"])["revision_notices"]


def test_old_version_matching_does_not_revive_a_stale_correction(dependencies):
    _, _, memory, jobs, _ = dependencies
    _, saved, later = case(dependencies)
    revised = memory.activate(memory.revise(saved["id"], "合成 RAG 评估的新表述")["id"])
    # This later run depended on the superseded memory itself, so it remains
    # ineligible; finding an old wording must not bypass that dependency.
    assert not memory.derived_eligibility(later["run_id"])["eligible"]
    assert memory.recall("RAG", jobs[:1]) == [revised]


def test_old_version_matching_keeps_revision_material_scope(dependencies):
    repo, store, memory, jobs, _ = dependencies
    _, saved, later = case(dependencies, uses_memory=False)
    extra = Catalog(repo).evidence(jobs[1])
    later["scope"] = Catalog(repo).query(job_ids=jobs)
    later["evidence"].extend(extra)
    later["claims"][0]["evidence_ids"].append(extra[0]["id"])
    later["cognition_revisions"][0].update(
        new_claim_indices=[0], reason="SYNTHETIC_OUTSIDE_SCOPE_REASON"
    )
    store.save(later["run_id"], result=later)
    revised = memory.activate(memory.revise(saved["id"], "合成 RAG 评估的新表述")["id"])
    narrow = memory.recall("RAG", jobs[:1])[0]
    notice = narrow["revision_notices"][0]
    assert narrow["id"] == revised["id"] and notice["scope_limited"]
    assert "SYNTHETIC_OUTSIDE_SCOPE_REASON" not in str(notice)
    assert notice["memory_match"]["id"] == saved["id"]
    broad = memory.recall("RAG", jobs)[0]
    assert broad["revision_notices"][0]["reason"] == "SYNTHETIC_OUTSIDE_SCOPE_REASON"


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
