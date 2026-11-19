"""修订/撤回的派生资格回归，使用实际隔离业务服务，不调用网络或模型。"""

from copy import deepcopy
from pathlib import Path

import pytest

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.dependencies import DependencyAudit
from work_observer.memory.service import MemoryService
from work_observer.reports.results import audit_result
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def dependencies(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    archive = RawArchive(tmp_path / "raw", [])
    jobs = [
        import_jd(
            repo,
            archive,
            ManualJD(
                title="合成研究岗位",
                company="合成公司",
                external_id=identity,
                description="负责 RAG 评估与 Python 开发。",
                data_kind="synthetic",
            ),
        )["job_id"]
        for identity in ("a", "b")
    ]
    store = ResearchStore(tmp_path / "custom-checkpoints.db", str(path.resolve()))
    repo.bind_research_store(store)
    yield repo, store, MemoryService(repo), jobs, archive
    store.close()
    repo.close()


def source(repo, store, jobs, *, memories=(), continued_from=(), project_id=None):
    if project_id:
        service = ProjectService(store)
        project = service.get(project_id)
        service.add(project_id, "合成 RAG 研究", revision=project["revision"])
        step = service.claim(project_id)
        identity = step["run_id"]
    else:
        identity = store.create({"question": "合成 RAG 研究", "job_ids": jobs})["id"]
    evidence = [item for job_id in jobs for item in Catalog(repo).evidence(job_id)]
    result = {
        "run_id": identity,
        "status": "completed",
        "question": "合成 RAG 研究",
        "scope": Catalog(repo).query(job_ids=jobs),
        "evidence": evidence,
        "memory_used": list(memories),
        "continued_from": list(continued_from),
        "claims": [
            {
                "text": "合成岗位负责 RAG 评估",
                "basis": "direct",
                "category": "task",
                "requirement": "unspecified",
                "evidence_ids": [evidence[0]["id"]],
            }
        ],
        "project_id": project_id,
    }
    store.save(identity, state="finished", result=result)
    if project_id:
        ProjectService(store).finish(project_id, step["id"], state="completed")
    return result


def accept(memory, result, kind="knowledge", *, evidence=None, job_id=None):
    row = memory.create(
        kind,
        "合成 RAG 派生认识",
        source_run_id=result["run_id"],
        evidence=evidence
        if evidence is not None
        else result["evidence"]
        if kind == "knowledge"
        else None,
        job_id=job_id,
        origin="agent",
    )
    return memory.activate(row["id"])


def test_revision_stops_multilevel_knowledge_hypothesis_method_without_erasing_history(
    dependencies,
):
    repo, store, memory, jobs, _ = dependencies
    preference = memory.create("preference", "只关注 RAG 开发", subject="工作方向")
    first = source(repo, store, jobs[:1], memories=[preference])
    knowledge = accept(memory, first)
    second = source(repo, store, jobs[:1], memories=[knowledge], continued_from=[first["run_id"]])
    hypothesis = accept(memory, second, "hypothesis")
    method = accept(memory, second, "method")
    assert {knowledge["id"], hypothesis["id"], method["id"]} <= {
        row["id"] for row in memory.recall("RAG", jobs[:1])
    }
    updated = memory.revise(preference["id"], "只关注 RAG 测试，不再采用旧开发方向")
    assert memory.recall("RAG", jobs[:1]) == [updated]
    assert all(
        not memory.validity(row["id"])["eligible"] for row in (knowledge, hypothesis, method)
    )
    assert all(
        row["status"] == "active"
        for row in memory.list()
        if row["id"] in {knowledge["id"], hypothesis["id"], method["id"]}
    )
    assert audit_result(second, repo)["stale_dependencies"]
    with pytest.raises(ProbeError, match="MEMORY_DERIVED_DEPENDENCY_STALE"):
        memory.activate(knowledge["id"])
    revised = memory.revise(knowledge["id"], "改写文字也不能洗掉旧来源依赖")
    with pytest.raises(ProbeError, match="MEMORY_DERIVED_DEPENDENCY_STALE"):
        memory.activate(revised["id"])
    assert store.get(first["run_id"])["result"] == first


def test_withdrawal_conflict_and_effective_time_are_transitive(dependencies):
    repo, store, memory, jobs, _ = dependencies
    pref = memory.create(
        "preference", "RAG 上海", subject="地点", valid_until="2077-01-01T00:00:00Z"
    )
    run = source(repo, store, jobs[:1], memories=[pref])
    derived = accept(memory, run)
    assert not memory.audit(derived["id"], at="2078-01-01T00:00:00Z")["eligible"]
    conflicting = memory.create("preference", "RAG 北京", subject="地点")
    assert conflicting["status"] == "conflict"
    assert not memory.validity(derived["id"])["eligible"]
    memory.resolve(conflicting["id"], "accept")
    assert not memory.validity(derived["id"])["eligible"]
    independent = source(repo, store, jobs[:1], memories=[conflicting])
    # 源结果引用的是候选当时的状态，但同ID经明确采纳后版本一致，当前可核验。
    fresh = accept(memory, independent)
    memory.withdraw(conflicting["id"])
    assert not memory.validity(fresh["id"])["eligible"]


def test_single_job_anchor_from_two_job_run_remains_usable_for_that_job(dependencies):
    repo, store, memory, jobs, _ = dependencies
    run = source(repo, store, jobs)
    anchored = accept(memory, run, evidence=Catalog(repo).evidence(jobs[0]), job_id=jobs[0])
    assert memory.recall("RAG", [jobs[0]]) == [anchored]
    assert not memory.recall("RAG", [jobs[1]])
    assert memory.derived_eligibility(run["run_id"], job_ids=[jobs[0]])["eligible"]


def test_global_summary_cannot_launder_project_memory_or_other_job_correction(dependencies):
    repo, store, memory, jobs, _ = dependencies
    project = ProjectService(store).create("合成项目", "RAG", jobs)
    scoped = memory.create("preference", "RAG 仅此项目参考", project_id=project["id"])
    run = source(repo, store, jobs[:1], memories=[scoped], project_id=project["id"])
    global_knowledge = accept(memory, run)
    assert global_knowledge in memory.recall("RAG", jobs[:1], project_id=project["id"])
    assert not memory.recall("RAG", jobs[:1])
    assert not memory.recall("RAG", jobs[:1], project_id="f" * 32)
    correction = memory.create("correction", "RAG 另一岗位的明确纠正", job_id=jobs[1])
    two_job = source(repo, store, jobs, memories=[correction])
    single_anchor = accept(
        memory, two_job, evidence=Catalog(repo).evidence(jobs[0]), job_id=jobs[0]
    )
    assert single_anchor not in memory.recall("RAG", jobs[:1])
    assert single_anchor in memory.recall("RAG", jobs)


def test_missing_unfinished_and_mismatched_source_evidence_cannot_be_accepted(dependencies):
    repo, store, memory, jobs, _ = dependencies
    pending = store.create({"question": "尚未完成"})
    for identity in ("a" * 32, pending["id"]):
        row = memory.create("method", "RAG 未完成研究方法", source_run_id=identity)
        with pytest.raises(ProbeError, match="MEMORY_DERIVED_DEPENDENCY_STALE"):
            memory.activate(row["id"])
    completed = source(repo, store, jobs[:1])
    wrong = memory.create(
        "knowledge",
        "不能把另一份JD冒充该运行所得",
        evidence=Catalog(repo).evidence(jobs[1]),
        source_run_id=completed["run_id"],
    )
    with pytest.raises(ProbeError, match="MEMORY_DERIVED_DEPENDENCY_STALE"):
        memory.activate(wrong["id"])


def test_bound_custom_store_remains_authoritative_after_pointer_close_and_namespace_isolated(
    dependencies,
):
    repo, store, memory, jobs, _ = dependencies
    run = source(repo, store, jobs[:1])
    row = accept(memory, run)
    store.close()
    repo.research_store = None
    assert memory.validity(row["id"])["eligible"]
    fresh_repo = Repository(Path(repo.engine.url.database))
    try:
        assert not MemoryService(fresh_repo).validity(row["id"])["eligible"]
        foreign = ResearchStore(repo.research_store_path, "foreign-namespace")
        try:
            with pytest.raises(ProbeError, match="RESEARCH_NAMESPACE_MISMATCH"):
                fresh_repo.bind_research_store(foreign)
        finally:
            foreign.close()
    finally:
        fresh_repo.close()
    # fixture可重复close，连接关闭本身不影响只读审计保存路径。


def test_continued_from_cycles_and_budget_fail_closed(dependencies):
    repo, store, memory, jobs, _ = dependencies
    first = source(repo, store, jobs[:1])
    second = source(repo, store, jobs[:1], continued_from=[first["run_id"]])
    row = accept(memory, second)
    changed = deepcopy(first)
    changed["continued_from"] = [second["run_id"]]
    store.save(first["run_id"], result=changed)
    audit = memory.validity(row["id"])
    assert not audit["eligible"]
    assert "dependency_cycle" in {issue["reason"] for issue in audit["dependency_issues"]}
    bounded = DependencyAudit(repo, max_nodes=1).run(second["run_id"])
    assert not bounded["eligible"]
    assert "dependency_budget_exceeded" in {issue["reason"] for issue in bounded["issues"]}


def test_method_without_own_evidence_still_invalidates_when_source_jd_changes(dependencies):
    repo, store, memory, jobs, archive = dependencies
    run = source(repo, store, jobs[:1])
    method = accept(memory, run, "method")
    import_jd(
        repo,
        archive,
        ManualJD(
            title="合成研究岗位",
            company="合成公司",
            external_id="a",
            description="新职责为人工资料整理。",
            data_kind="synthetic",
        ),
    )
    assert not memory.validity(method["id"])["eligible"]
    assert not memory.recall("RAG", jobs[:1])


def test_explicitly_resolving_original_value_restores_unchanged_dependency(dependencies):
    repo, store, memory, jobs, _ = dependencies
    original = memory.create("preference", "RAG 原偏好", subject="方向")
    run = source(repo, store, jobs[:1], memories=[original])
    knowledge = accept(memory, run)
    memory.create("preference", "RAG 新候选偏好", subject="方向")
    assert not memory.validity(knowledge["id"])["eligible"]
    memory.resolve(original["id"], "accept")
    assert memory.validity(knowledge["id"])["eligible"]
    assert knowledge in memory.recall("RAG", jobs[:1])


def test_unrelated_job_change_does_not_invalidate_explicit_single_job_anchor(dependencies):
    repo, store, memory, jobs, archive = dependencies
    run = source(repo, store, jobs)
    knowledge = accept(memory, run, evidence=Catalog(repo).evidence(jobs[0]), job_id=jobs[0])
    method = accept(memory, run, "method")
    import_jd(
        repo,
        archive,
        ManualJD(
            title="合成研究岗位",
            company="合成公司",
            external_id="b",
            description="另一个岗位后来改为人工业务整理。",
            data_kind="synthetic",
        ),
    )
    assert memory.validity(knowledge["id"])["eligible"]
    assert knowledge in memory.recall("RAG", jobs[:1])
    assert not memory.validity(method["id"])["eligible"]
    assert audit_result(run, repo)["stale_dependencies"]


def test_replacing_source_metadata_cannot_silently_rebind_frozen_evidence(dependencies):
    import hashlib

    from sqlalchemy.orm import Session

    from work_observer.storage.models import SourceDocument

    repo, store, memory, jobs, _ = dependencies
    run = source(repo, store, jobs[:1])
    knowledge = accept(memory, run)
    with Session(repo.engine) as session, session.begin():
        document = session.get(SourceDocument, run["evidence"][0]["document_id"])
        original = Path(document.path).read_bytes()
        changed = original + b"\n"
        Path(document.path).write_bytes(changed)
        document.sha256 = hashlib.sha256(changed).hexdigest()
    audited = memory.validity(knowledge["id"])
    assert not audited["eligible"]
    assert "source_reference_changed" in {issue["reason"] for issue in audited["dependency_issues"]}


@pytest.mark.parametrize("reviewer_kind", ["human", "agent_assisted"])
def test_rejection_blocks_derived_memory_until_human_reassessment(dependencies, reviewer_kind):
    from work_observer.quality.reviews import QualityReviewService
    from work_observer.quality.service import DIMENSIONS

    repo, store, memory, jobs, _ = dependencies
    run = source(repo, store, jobs[:1])
    knowledge = accept(memory, run)
    quality = QualityReviewService(store, repo)
    packet = quality.packet(run["run_id"])
    review = {
        "reviewer": "合成人审动作",
        "reviewer_kind": reviewer_kind,
        "decision": "reject",
        "note": "合成机制测试，不是实际人类标注",
        "result_sha256": packet["result_sha256"],
        "dimensions": {key: {"rating": "fail", "reason": "合成拒绝"} for key in DIMENSIONS},
        "claim_reviews": [
            {"index": 0, "support": "unsupported", "requirement": "correct", "note": "合成拒绝"}
        ],
    }
    quality.submit(run["run_id"], review)
    assert not memory.validity(knowledge["id"])["eligible"]
    quality.submit(
        run["run_id"], {**review, "reviewer_kind": "agent_assisted", "decision": "pending"}
    )
    assert not memory.validity(knowledge["id"])["eligible"]
    approved = {
        **review,
        "reviewer_kind": "human",
        "decision": "approve",
        "dimensions": {key: {"rating": "pass", "reason": "合成重新核对"} for key in DIMENSIONS},
        "claim_reviews": [
            {"index": 0, "support": "supported", "requirement": "correct", "note": "合成重新核对"}
        ],
    }
    quality.submit(run["run_id"], approved)
    assert memory.validity(knowledge["id"])["eligible"]
