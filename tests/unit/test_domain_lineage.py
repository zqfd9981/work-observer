"""Merged and split map definitions retain their actual source scope."""

from copy import deepcopy

from test_dependency_eligibility import dependencies as dependencies
from test_dependency_eligibility import source
from test_map_revision_notices import make_revision, setup_map

from work_observer.memory.dependencies import DependencyAudit
from work_observer.memory.lifecycle import forget_personal
from work_observer.research.projects import ProjectService
from work_observer.retrieval.unified import UnifiedRetrieval


def test_forgetting_source_context_clears_merged_definitions_and_consumers(dependencies, tmp_path):
    repo, store, memory, jobs, _ = dependencies
    private = memory.create("preference", "合成待忘记的研究背景")
    original, domains, _, knowledge = setup_map(dependencies)
    original["memory_used"] = [private]
    store.save(original["run_id"], result=original)
    merged = combine(knowledge, domains)
    found = knowledge.browse_for_research(["RAG"], job_ids=jobs, public_document_ids=[])
    child = source(repo, store, jobs)
    child["knowledge_used"] = found["dependencies"]
    store.save(child["run_id"], result=child)
    raw = [repo.job(identity) for identity in jobs]
    erased = forget_personal(repo, store, private["id"], tmp_path / "reports")
    assert {original["run_id"], child["run_id"]} <= set(erased["affected_run_ids"])
    listed = next(
        row for row in knowledge.list_domains(include_history=True) if row["id"] == merged["id"]
    )
    assert listed["status"] == "invalidated" and not listed["supporting_claims"]
    assert not listed["revision_notices"]
    assert raw == [repo.job(identity) for identity in jobs]


def combine(knowledge, domains, *, kind="merge", key="merged_rag"):
    row = knowledge.propose_domain(
        key,
        "合成 RAG 组合工作",
        "RAG 工作的合并或拆分假设，非真实知识",
        change_kind=kind,
        related_ids=[row["id"] for row in domains],
    )
    return knowledge.review_domain(row["id"], "accept", "合成机制核对")


def test_merged_then_split_definition_cannot_escape_project_or_source_scope(dependencies):
    repo, store, _, jobs, _ = dependencies
    project = ProjectService(store).create(
        "合成限定项目", "RAG", jobs, max_calls=60, max_seconds=1800
    )
    original, domains, _, knowledge = setup_map(dependencies, project["id"])
    before = deepcopy(store.get(original["run_id"]))
    merged = combine(knowledge, domains)
    split = combine(knowledge, [merged], kind="split", key="split_rag")
    assert not knowledge.browse_for_research(["RAG"], job_ids=jobs, public_document_ids=[])[
        "domains"
    ]
    assert not knowledge.browse_for_research(
        ["RAG"], job_ids=[], public_document_ids=[], project_id=project["id"]
    )["domains"]
    scoped = knowledge.browse_for_research(
        ["RAG"], job_ids=jobs, public_document_ids=[], project_id=project["id"]
    )
    assert {row["id"] for row in scoped["domains"]} == {split["id"]}
    assert original["run_id"] in scoped["source_run_ids"]
    assert {
        claim["claim_index"]
        for packet in scoped["supporting_findings"]
        for claim in packet["claims"]
    } == {0, 1}
    later = make_revision(dependencies, original, project_id=project["id"])
    recalled = knowledge.browse_for_research(
        ["RAG"], job_ids=jobs, public_document_ids=[], project_id=project["id"]
    )
    assert recalled["domains"][0]["revision_notices"][0]["run_id"] == later["run_id"]
    retrieved = UnifiedRetrieval(repo).search(
        ["RAG"], job_ids=jobs, public_document_ids=[], project_id=project["id"]
    )
    assert retrieved["domain_knowledge"]["supporting_findings"]
    # A forged narrower consumer cannot reuse the merged definition as generic.
    assert knowledge.audit_dependencies(
        scoped["dependencies"], job_ids=jobs, public_document_ids=[], project_id=None
    )
    consumer = {
        **original,
        "project_id": None,
        "knowledge_used": scoped["dependencies"],
        "evidence": [],
        "claims": [],
    }
    assert not DependencyAudit(repo).result(consumer)["eligible"]
    used = source(repo, store, jobs, project_id=project["id"])
    used["knowledge_used"] = scoped["dependencies"]
    store.save(used["run_id"], result=used)
    assert DependencyAudit(repo).run(used["run_id"])["eligible"]
    indirect = {**consumer, "knowledge_used": [], "continued_from": [used["run_id"]]}
    assert not DependencyAudit(repo).result(indirect)["eligible"]
    assert store.get(original["run_id"]) == before


def test_manual_revision_of_a_merge_keeps_both_sources_and_stops_on_source_invalidation(
    dependencies,
):
    _, store, _, jobs, _ = dependencies
    first, domains, _, knowledge = setup_map(dependencies)
    second, other, _, _ = setup_map(dependencies)
    merged = combine(knowledge, [domains[0], other[1]])
    revised = knowledge.propose_domain(
        merged["domain_key"],
        merged["name"],
        "合成 RAG 组合的细化定义",
        previous_id=merged["id"],
        change_kind="revise",
    )
    knowledge.review_domain(revised["id"], "accept", "合成改写核对")
    found = knowledge.browse_for_research(["RAG"], job_ids=jobs, public_document_ids=[])
    row = next(row for row in found["domains"] if row["id"] == revised["id"])
    assert {context["run_id"] for context in row["source_contexts"]} == {
        first["run_id"],
        second["run_id"],
    }
    assert {packet["run_id"] for packet in found["supporting_findings"]} == {
        first["run_id"],
        second["run_id"],
    }
    store.invalidate_runs([second["run_id"]])
    listed = next(row for row in knowledge.list_domains() if row["id"] == revised["id"])
    assert listed["stale"]
    assert revised["id"] not in {
        row["id"]
        for row in knowledge.browse_for_research(["RAG"], job_ids=jobs, public_document_ids=[])[
            "domains"
        ]
    }
