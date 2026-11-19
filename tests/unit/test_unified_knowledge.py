"""统一原文与领域知识机制验收；全部材料为明确的隔离合成资料。"""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.analysis.profiles import ProfileService
from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.connectors.public_models import PublicDocument
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.service import MemoryService
from work_observer.reports.results import audit_result
from work_observer.research.agent import research
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog, Filters
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import JobObservation
from work_observer.storage.repository import Repository


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "knowledge.db"
    upgrade(path)
    repository = Repository(path)
    archive = RawArchive(tmp_path / "raw")

    def add_job(identity, text="构建 Python 智能体，交付业务应用。", **kwargs):
        return import_jd(
            repository,
            archive,
            ManualJD(
                title="合成岗位",
                company="合成公司" + identity,
                external_id=identity,
                description=text,
                **kwargs,
            ),
        )["job_id"]

    def add_public(
        text="合成业务介绍：提供 Python 智能体平台。",
        url="https://example.com/product",
        at="2026-11-01T00:00:00+00:00",
    ):
        identity = uuid4().hex
        source = tmp_path / f"{identity}.txt"
        source.write_bytes(text.encode())
        digest = hashlib.sha256(text.encode()).hexdigest()
        with Session(repository.engine) as session, session.begin():
            row = PublicDocument(
                id=identity,
                url=url,
                final_url=url,
                publisher="example.com",
                title="合成公开资料",
                content_type="text/plain",
                path=str(source),
                sha256=digest,
                text_sha256=digest,
                text=text,
                observed_at=at,
                source_published_at=None,
                extractor_version="synthetic-fixture",
            )
            session.add(row)
            session.flush()
            return identity, PublicDocumentService._evidence(row)[0]

    yield repository, add_job, add_public
    repository.close()


def test_same_glyph_radicals_match_without_rewriting_citations(corpus):
    repository, add_job, add_public = corpus
    text = "合成资料：处理上下⽂溢出、长⽂档问答和⼯具调用；编号①号。"
    job = add_job("radicals", text)
    document, _ = add_public(text=text)
    found = UnifiedRetrieval(repository).search(
        ["上下文溢出"],
        job_ids=[job],
        public_document_ids=[document],
        aliases=False,
        include_knowledge=False,
    )
    assert found["matching_jobs"] == found["matching_public_documents"] == 1
    assert len(found["evidence"]) == 2
    for evidence in found["evidence"]:
        assert evidence["quote"] == text[evidence["start"] : evidence["end"]]
        assert "上下⽂溢出" in evidence["quote"]
        if evidence.get("public_document_id"):
            assert evidence["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert repository.job(job)["current"]["description_text"] == text
    catalog = Catalog(repository)
    assert catalog.search(["长文档问答"], job_ids=[job])["matching_jobs"] == 1
    assert catalog.evidence(job, terms=["工具调用"])
    assert catalog.query(Filters(keyword="长文档问答"), job_ids=[job])["counts"]["matched"] == 1
    stats = RetrievalService(repository).stats(["长文档问答"], job_ids=[job])
    assert stats["statistics"][0]["literal_jobs"] == 1
    assert not UnifiedRetrieval(repository).search(
        ["1号"],
        job_ids=[job],
        public_document_ids=[document],
        aliases=False,
        include_knowledge=False,
    )["evidence"]  # No broad compatibility folding of unrelated characters.


def active_domain(repository, key="business_application"):
    service = DomainKnowledgeService(repository)
    row = service.propose_domain(
        key, "合成领域", "开发并交付业务应用", inclusion="应用开发", exclusion="未知"
    )
    return service.review_domain(row["id"], "accept", "隔离测试人工审核动作")


def completed_source(repository, store, job):
    repository.bind_research_store(store)
    run = store.create({"question": "合成上游研究"})
    evidence = Catalog(repository).evidence(job)
    store.save(
        run["id"],
        state="finished",
        result={
            "run_id": run["id"],
            "status": "completed",
            "scope": Catalog(repository).query(job_ids=[job]),
            "evidence": evidence,
            "claims": [
                {
                    "category": "task",
                    "requirement": "unspecified",
                    "basis": "direct",
                    "text": "合成原文研究",
                    "evidence_ids": [evidence[0]["id"]],
                }
            ],
            "memory_used": [],
            "context_memory_used": [],
            "knowledge_used": [],
            "continued_from": [],
        },
    )
    return run


def test_unified_separates_originals_from_derived_and_counts_before_limit(corpus):
    repository, add, public = corpus
    jobs = [add(str(index)) for index in range(3)]
    public_id, _ = public()
    evidence = Catalog(repository).evidence(jobs[0])
    memory = MemoryService(repository)
    candidate = memory.create("knowledge", "Python 智能体应用交付", evidence=evidence)
    memory.activate(candidate["id"])
    result = UnifiedRetrieval(repository).search(["Python"], limit=1)
    assert result["sample"]["denominator"] == 3
    assert result["matching_jobs"] == 3
    assert result["public_scope_total"] == result["matching_public_documents"] == 1
    assert len(result["evidence"]) == 1
    assert all(not item["derived"] for item in result["evidence"])
    assert result["knowledge"][0]["independent_source"] is False
    assert result["knowledge"][0]["evidence"][0]["job_id"] == jobs[0]
    scoped = UnifiedRetrieval(repository).search(
        ["Python"], job_ids=[], public_document_ids=[public_id]
    )
    assert scoped["sample"]["scope_total"] == 0
    assert not scoped["knowledge"]
    assert scoped["evidence"][0]["evidence_kind"] == "public_document"


def test_unified_public_latest_explicit_history_and_integrity(corpus):
    repository, _, public = corpus
    old, _ = public("旧合成 Python 产品", at="2026-11-01T00:00:00+00:00")
    new, _ = public("新合成 Java 产品", at="2026-11-02T00:00:00+00:00")
    service = UnifiedRetrieval(repository)
    assert service.search(["Python"])["evidence"] == []
    frozen = service.search(["Python"], public_document_ids=[old])
    assert frozen["evidence"][0]["public_document_id"] == old
    historical = service.search(["Python"], as_of="2026-11-01T12:00:00+00:00")
    assert historical["evidence"][0]["public_document_id"] == old
    with Session(repository.engine) as session:
        path = Path(session.get(PublicDocument, new).path)
    path.write_bytes(b"changed")
    missing = service.search(["Java"])
    assert not missing["evidence"]
    assert missing["excluded_integrity_ids"] == [new]


def test_unified_public_search_covers_late_body_with_exact_offsets(corpus):
    repository, _, public = corpus
    identity, _ = public("无关合成资料" * 1500 + "latekeyword")
    result = UnifiedRetrieval(repository).search(["latekeyword"])
    assert result["evidence"][0]["start"] > 5600
    with Session(repository.engine) as session:
        text = session.get(PublicDocument, identity).text
    for evidence in result["evidence"]:
        assert text[evidence["start"] : evidence["end"]] == evidence["quote"]
    assert result["context_characters"] <= 7000


def test_long_public_source_does_not_crowd_short_job_sources(corpus):
    repository, add, public = corpus
    jobs = [add(str(index), "Python 接口任务") for index in range(3)]
    public("Python " * 3000)
    result = UnifiedRetrieval(repository).search(["Python"], limit=4)
    assert {item["job_id"] for item in result["evidence"] if item.get("job_id")} == set(jobs)
    assert (
        len(
            {
                item["public_document_id"]
                for item in result["evidence"]
                if item.get("public_document_id")
            }
        )
        == 1
    )


def test_domain_version_review_preserves_old_definition_and_invalidates_old_relation(corpus):
    repository, add, _ = corpus
    job = add("a")
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository)
    relation = service.propose_relation(
        domain["id"],
        "task",
        "构建应用",
        "deliverable",
        "业务应用",
        Catalog(repository).evidence(job),
    )
    service.review_relation(relation["id"], "accept", "合成审核")
    revised = service.propose_domain(
        domain["domain_key"],
        "新领域定义",
        "业务系统开发与运营",
        previous_id=domain["id"],
        change_kind="revise",
    )
    assert service.list_relations()[0]["stale"] is False
    service.review_domain(revised["id"], "accept", "合成审核修订定义")
    assert service.list_relations()[0]["stale"]
    history = service.list_domains(include_history=True)
    assert {row["status"] for row in history} == {"active", "superseded"}
    with pytest.raises(ProbeError, match="DOMAIN_VERSION_CONFLICT"):
        service.propose_domain(
            domain["domain_key"],
            "重复",
            "错误旧版本",
            previous_id=domain["id"],
            change_kind="revise",
        )


def test_domain_merge_and_split_are_candidates_until_reviewed(corpus):
    repository, _, _ = corpus
    service = DomainKnowledgeService(repository)
    old = active_domain(repository)
    other = active_domain(repository, "delivery")
    merged = service.propose_domain(
        "application_delivery",
        "应用交付",
        "应用与交付合并定义",
        change_kind="merge",
        related_ids=[old["id"], other["id"]],
    )
    assert merged["status"] == "candidate"
    assert len([row for row in service.list_domains() if row["status"] == "active"]) == 2
    service.review_domain(merged["id"], "accept", "合成审核合并")
    assert {row["status"] for row in service.list_domains(True)} == {"active", "retired"}
    split = service.propose_domain(
        "application_build",
        "应用构建",
        "拆分构建范围",
        change_kind="split",
        related_ids=[merged["id"]],
    )
    service.review_domain(split["id"], "reject", "合成审核拒绝拆分")
    assert any(
        row["id"] == merged["id"] and row["status"] == "active" for row in service.list_domains()
    )


def test_relation_conflict_requires_explicit_prior_review_and_retains_counterexample(corpus):
    repository, add, _ = corpus
    first = add("a", "任务要求 Python，交付接口。")
    second = add("b", "任务只要求 Java，不要求 Python。")
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository)
    original = service.propose_relation(
        domain["id"], "task", "构建接口", "tool", "Python", Catalog(repository).evidence(first)
    )
    service.review_relation(original["id"], "accept", "合成首条审核")
    disputed = service.propose_relation(
        domain["id"],
        "task",
        "构建接口",
        "tool",
        "Java",
        Catalog(repository).evidence(second),
        counterevidence=Catalog(repository).evidence(first),
        conflict_ids=[original["id"]],
    )
    assert disputed["status"] == "conflicted"
    original_output = next(row for row in service.list_relations() if row["id"] == original["id"])
    assert original_output["stale"]
    with pytest.raises(ProbeError, match="RELATION_CONFLICT_REQUIRES_REVIEW"):
        service.review_relation(disputed["id"], "accept", "不能自动覆盖")
    service.review_relation(original["id"], "withdraw", "合成审核保留反例后撤回普遍判断")
    accepted = service.review_relation(disputed["id"], "accept", "合成审核限定范围")
    assert len(accepted["counterevidence"]) == 1
    assert accepted["scope"]["job_ids"] == [second]
    assert accepted["scope"]["counter_job_ids"] == [first]


def test_relation_public_background_does_not_prove_job_duties(corpus):
    repository, _, public = corpus
    _, evidence = public()
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository)
    with pytest.raises(ProbeError, match="RELATION_JOB_EVIDENCE_REQUIRED"):
        service.propose_relation(domain["id"], "task", "构建应用", "tool", "Python", [evidence])
    relation = service.propose_relation(
        domain["id"], "business", "平台", "business", "应用交付", [evidence]
    )
    assert not relation["scope"]["job_ids"]
    service.review_relation(relation["id"], "accept", "合成审核仅业务背景")


def test_relation_stale_on_changed_source_and_forget_scrubs_derived_text(corpus, tmp_path):
    repository, add, _ = corpus
    job = add("a")
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository)
    store = ResearchStore(tmp_path / "source-checkpoints.db", str(repository.engine.url.database))
    source = completed_source(repository, store, job)
    store.close()
    relation = service.propose_relation(
        domain["id"],
        "task",
        "构建应用",
        "tool",
        "Python",
        Catalog(repository).evidence(job),
        source_run_id=source["id"],
    )
    service.review_relation(relation["id"], "accept", "合成审核")
    add("a", "全新 Java 职责")
    assert service.list_relations()[0]["stale"]
    invalidated = service.invalidate_research([source["id"]])
    assert invalidated["invalidated_relation_ids"] == [relation["id"]]
    assert not service.list_relations()
    row = service.list_relations(include_history=True)[0]
    assert row["source_text"] == "[上游研究已失效]" and row["evidence"] == []
    assert Catalog(repository).evidence(job)


def test_domain_collection_full_denominator_corrections_and_scope_not_top_k(corpus):
    repository, add, _ = corpus
    jobs = [add(str(index), city="上海") for index in range(4)]
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository)
    for job in jobs[:2]:
        row = service.propose_relation(
            domain["id"],
            "task",
            "应用开发",
            "deliverable",
            "应用",
            Catalog(repository).evidence(job),
        )
        service.review_relation(row["id"], "accept", "合成审核")
    ProfileService(repository).set_domain_correction(
        jobs[1], ["agent_platform"], "合成明确人工纠正"
    )
    result = service.collection(domain["id"], limit=1)
    assert result["counts"] == {"scope_total": 4, "matched": 1, "unknown": 2, "excluded": 1}
    assert result["truncated"] and len(result["jobs"]) == 1
    scoped = service.collection(domain["id"], job_ids=[jobs[3]])
    assert scoped["counts"] == {"scope_total": 1, "matched": 0, "unknown": 1, "excluded": 0}


def test_domain_collection_cannot_use_later_review_for_past_scope(corpus):
    repository, add, _ = corpus
    job = add("a")
    with Session(repository.engine) as session:
        cutoff = session.scalar(select(JobObservation.processed_at))
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository)
    row = service.propose_relation(
        domain["id"], "task", "应用开发", "deliverable", "应用", Catalog(repository).evidence(job)
    )
    service.review_relation(row["id"], "accept", "合成审核发生在截止后")
    assert service.collection(domain["id"])["counts"]["matched"] == 1
    assert service.collection(domain["id"], as_of=cutoff)["counts"]["matched"] == 0


def test_dynamic_domain_correction_does_not_silently_adopt_changed_definition(corpus):
    repository, add, _ = corpus
    job = add("a")
    service = DomainKnowledgeService(repository)
    domain = active_domain(repository, "custom_delivery")
    corrected = service.correct_job_domains(job, [domain["id"]], "合成人工明确纠正")
    assert corrected["status"] == "active"
    assert service.collection(domain["id"])["counts"]["matched"] == 1
    profiles = ProfileService(repository)
    initial_profile = asyncio.run(profiles.analyze(job, Settings(), offline=True))
    assert initial_profile["result"]["effective_domains"][0]["definition_id"] == domain["id"]
    assert initial_profile["result"]["effective_domains"][0]["status"] == "user_corrected"
    revised = service.propose_domain(
        domain["domain_key"],
        "新交付领域",
        "新版本扩大定义边界",
        previous_id=domain["id"],
        change_kind="revise",
    )
    service.review_domain(revised["id"], "accept", "合成审核新口径")
    result = service.collection(revised["id"])
    assert result["counts"]["matched"] == 0 and result["counts"]["unknown"] == 1
    assert result["jobs"][0]["correction_definition_ids"] == [domain["id"]]
    old_profile = profiles.get(job)
    assert old_profile["stale"]
    assert old_profile["result"]["effective_domains"][0]["status"] == "user_corrected_stale"
    assert old_profile["result"]["effective_domains"][0]["definition_id"] == domain["id"]


class ArchivedToolModel:
    """明确工具替身：只验证数据范围、引用与预算，不声称真实模型语义质量。"""

    def __init__(self, pause=False, force_task=False):
        self.pause, self.force_task = pause, force_task
        self.waiting = asyncio.Event()
        self.retrieved = None

    async def turn(self, history):
        outputs = [
            json.loads(item["output"])
            for item in history
            if item.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "query_jobs", {}
        elif len(outputs) == 1:
            if self.pause:
                self.waiting.set()
                await asyncio.Event().wait()
            name, arguments = "search_archived_sources", {"terms": ["Python"]}
        else:
            self.retrieved = outputs[-1]
            evidence = self.retrieved["evidence"]
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task"
                            if self.force_task or item.get("job_id")
                            else "business",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "合成引用范围机制验收",
                            "evidence_ids": [item["citation_key"]],
                        }
                        for item in evidence
                    ],
                    "gaps": ["合成工具替身，不构成真实语义质量证明。"],
                },
            )
        item = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": name,
        }
        return [item], item


def test_archived_agent_resume_freezes_latest_url_job_scope_time_and_unknown_filters(
    corpus, tmp_path
):
    repository, add, public = corpus
    job = add("a", "最初 Python 任务")
    old, _ = public("旧版本 Python 合成业务", at="2026-11-01T00:00:00+00:00")
    selected, _ = public("当前 Python 合成业务", at="2026-11-02T00:00:00+00:00")
    store = ResearchStore(tmp_path / "agent-checkpoints.db", str(repository.engine.url.database))
    try:

        async def scenario():
            run = store.create({"question": "Python 合成验证"})
            initial = ArchivedToolModel(pause=True)
            task = asyncio.create_task(
                research(
                    repository,
                    "Python 合成验证",
                    Settings(),
                    job_ids=[job],
                    filters=Filters(salary_min=20000),
                    model=initial,
                    checkpoint=(store, run["id"]),
                    max_calls=6,
                )
            )
            await asyncio.wait_for(initial.waiting.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            add("a", "后续 Java 职责", salary="40-50K")
            outside = add("outside", "范围外 Python 任务")
            later, _ = public("后来 Python 产品", at=now())
            continuation = ArchivedToolModel()
            result = await research(
                repository,
                "Python 合成验证",
                Settings(),
                model=continuation,
                checkpoint=(store, run["id"]),
                resume=True,
            )
            assert result["status"] == "completed" and result["model_calls"] == 4
            assert result["scope"]["archived_public_ids"] == [selected]
            assert result["scope"]["archived_public_total"] == 1
            assert not result["scope"]["archived_public_truncated"]
            assert continuation.retrieved["sample"]["unknown"] == 1
            assert continuation.retrieved["sample"]["matched"] == 0
            assert {item["job_id"] for item in result["evidence"] if item.get("job_id")} == {job}
            assert {
                item["public_document_id"]
                for item in result["evidence"]
                if item.get("public_document_id")
            } == {selected}
            assert (
                outside not in str(result["evidence"])
                and old not in str(result["evidence"])
                and later not in str(result["evidence"])
            )
            assert any(item["quote"] == "最初 Python 任务" for item in result["evidence"])

        asyncio.run(scenario())
    finally:
        store.close()


def test_public_only_agent_business_direct_and_offline_context_bounded(corpus):
    repository, _, public = corpus
    public("Python 合成业务背景。" * 2000)
    model = ArchivedToolModel()
    result = asyncio.run(
        research(repository, "Python 公开业务是什么", Settings(), model=model, max_calls=3)
    )
    assert result["status"] == "completed" and result["scope"]["counts"]["scope_total"] == 0
    assert all(item["category"] == "business" for item in result["claims"])
    offline = asyncio.run(research(repository, "公开业务", Settings(), offline=True))
    assert offline["status"] == "evidence_only" and offline["model_calls"] == 0
    assert offline["evidence"] and offline["offline_context_characters"] <= 7000
    assert all(item["evidence_kind"] == "public_document" for item in offline["evidence"])


def test_public_only_agent_cannot_turn_business_material_into_direct_job_duty(corpus):
    repository, _, public = corpus
    public()
    result = asyncio.run(
        research(
            repository,
            "Python 职责",
            Settings(),
            model=ArchivedToolModel(force_task=True),
            max_calls=3,
        )
    )
    assert result["status"] == "incomplete" and not result["claims"]
    assert result["trace"][-1]["validation"] == "citation_or_coverage_rejected"


def test_archived_agent_resume_keeps_frozen_aliases_after_reviewed_strategy_change(
    corpus, tmp_path
):
    from work_observer.retrieval.enhanced import DEFAULT_ALIASES
    from work_observer.tracking.evaluation import StrategyService

    repository, add, _ = corpus
    job = add("a", "开发智能体平台")
    store = ResearchStore(tmp_path / "strategy-checkpoints.db", str(repository.engine.url.database))

    class SearchOnly:
        async def turn(self, history):
            item = {
                "type": "function_call",
                "name": "search_archived_sources",
                "arguments": json.dumps({"terms": ["Agent"]}),
                "call_id": "frozen-alias-check",
            }
            return [item], item

    try:

        async def scenario():
            run = store.create({"question": "合成别名冻结验证"})
            initial = ArchivedToolModel(pause=True)
            task = asyncio.create_task(
                research(
                    repository,
                    "合成别名冻结验证",
                    Settings(),
                    job_ids=[job],
                    model=initial,
                    checkpoint=(store, run["id"]),
                    max_calls=3,
                )
            )
            await asyncio.wait_for(initial.waiting.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            strategy = StrategyService(repository)
            candidate = strategy.create("合成策略切换", DEFAULT_ALIASES)
            assert strategy.evaluate(candidate["id"])["status"] == "accepted"
            strategy.activate(candidate["id"])
            assert UnifiedRetrieval(repository).search(["Agent"])["evidence"]
            result = await research(
                repository,
                "合成别名冻结验证",
                Settings(),
                model=SearchOnly(),
                checkpoint=(store, run["id"]),
                resume=True,
            )
            assert result["status"] == "incomplete" and result["model_calls"] == 3
            assert result["strategy"]["aliases"] == {} and not result["evidence"]

        asyncio.run(scenario())
    finally:
        store.close()


def reviewed_relation(repository, domain, job, *, source_run_id=None, **kwargs):
    service = DomainKnowledgeService(repository)
    row = service.propose_relation(
        domain["id"],
        "task",
        "开发 Python 应用",
        "deliverable",
        "业务接口",
        Catalog(repository).evidence(job),
        source_run_id=source_run_id,
        **kwargs,
    )
    return service.review_relation(row["id"], "accept", "合成关系审核，不作为真实语义评估")


def test_domain_knowledge_browse_enforces_project_positive_counter_and_public_scopes(corpus):
    repository, add, public = corpus
    job, other = add("a"), add("b")
    public_id, public_evidence = public()
    domain = active_domain(repository)
    service = DomainKnowledgeService(repository)
    allowed = reviewed_relation(repository, domain, job)
    reviewed_relation(repository, domain, job, counterevidence=Catalog(repository).evidence(other))
    reviewed_relation(repository, domain, job, project_id="b" * 32)
    mixed = service.propose_relation(
        domain["id"],
        "business",
        "Python 公司业务",
        "business",
        "平台",
        [*Catalog(repository).evidence(job), public_evidence],
    )
    service.review_relation(mixed["id"], "accept", "合成混合来源审核")
    result = service.browse_for_research(["Python"], job_ids=[job], public_document_ids=[])
    assert [row["id"] for row in result["relations"]] == [allowed["id"]]
    assert "evidence" not in result and "quote" not in str(result)
    expanded = service.browse_for_research(
        ["Python"], job_ids=[job, other], public_document_ids=[public_id], project_id="b" * 32
    )
    assert len(expanded["relations"]) == 4
    assert all(row["independent_source"] is False for row in expanded["relations"])
    assert len(expanded["domains"]) <= 6 and len(expanded["relations"]) <= 10
    service.correct_job_domains(job, [], "合成用户明确暂不归入任何领域")
    corrected = service.browse_for_research(
        ["Python"], job_ids=[job, other], public_document_ids=[public_id], project_id="b" * 32
    )
    assert not corrected["relations"]


class DomainToolModel:
    def __init__(self, job, pause=False, forged_first=False):
        self.job, self.pause, self.forged_first = job, pause, forged_first
        self.waiting = asyncio.Event()
        self.calls = 0

    async def turn(self, history):
        self.calls += 1
        outputs = [
            json.loads(item["output"])
            for item in history
            if item.get("type") == "function_call_output"
        ]
        if not outputs:
            name, arguments = "query_jobs", {}
        elif len(outputs) == 1:
            name, arguments = "browse_domain_knowledge", {"terms": ["Python"]}
        elif len(outputs) == 2 and self.pause:
            self.waiting.set()
            await asyncio.Event().wait()
        elif len(outputs) == 2 and self.forged_first:
            reference = outputs[-1]["relations"][0]["source_references"][0]["id"]
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "开发 Python 应用",
                            "evidence_ids": [reference],
                        }
                    ],
                    "gaps": [],
                },
            )
        elif not outputs[-1].get("evidence"):
            name, arguments = "read_job", {"job_id": self.job}
        else:
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "开发 Python 应用",
                            "evidence_ids": [outputs[-1]["evidence"][0]["citation_key"]],
                        }
                    ],
                    "gaps": ["合成工具机制测试"],
                },
            )
        item = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": name,
        }
        return [item], item


def test_domain_agent_records_derived_dependency_and_requires_original_reread(corpus, tmp_path):
    repository, add, _ = corpus
    job = add("a")
    store = ResearchStore(tmp_path / "domain-agent.db", str(repository.engine.url.database))
    try:
        source = completed_source(repository, store, job)
        domain = active_domain(repository)
        relation = reviewed_relation(repository, domain, job, source_run_id=source["id"])
        run = store.create({"question": "Python 任务"})
        result = asyncio.run(
            research(
                repository,
                "Python 任务",
                Settings(),
                job_ids=[job],
                model=DomainToolModel(job, forged_first=True),
                checkpoint=(store, run["id"]),
                max_calls=5,
            )
        )
        assert result["status"] == "completed" and result["model_calls"] == 5
        assert len(result["knowledge_used"]) == 2
        assert all(
            not ({"content", "definition", "quote", "source_text"} & set(item))
            for item in result["knowledge_used"]
        )
        assert source["id"] in result["continued_from"]
        assert run["id"] in store.dependent_runs([source["id"]])
        assert any(
            row.get("validation") == "citation_or_coverage_rejected" for row in result["trace"]
        )
        assert not audit_result(result, repository)["stale_knowledge"]
        DomainKnowledgeService(repository).review_relation(
            relation["id"], "withdraw", "合成明确撤回"
        )
        assert audit_result(result, repository)["stale_knowledge"]
    finally:
        store.close()


@pytest.mark.parametrize("change", ["withdraw", "definition", "source"])
def test_domain_agent_resume_rejects_changed_knowledge_before_any_new_model_call(
    corpus, tmp_path, change
):
    repository, add, _ = corpus
    job = add("a")
    domain = active_domain(repository)
    relation = reviewed_relation(repository, domain, job)
    store = ResearchStore(tmp_path / "domain-resume.db", str(repository.engine.url.database))
    try:

        async def scenario():
            run = store.create({"question": "Python 任务"})
            model = DomainToolModel(job, pause=True)
            task = asyncio.create_task(
                research(
                    repository,
                    "Python 任务",
                    Settings(),
                    job_ids=[job],
                    model=model,
                    checkpoint=(store, run["id"]),
                    max_calls=6,
                )
            )
            await asyncio.wait_for(model.waiting.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            service = DomainKnowledgeService(repository)
            if change == "withdraw":
                service.review_relation(relation["id"], "withdraw", "合成撤回关系")
            elif change == "definition":
                updated = service.propose_domain(
                    domain["domain_key"],
                    "新定义",
                    "新的 Python 交付边界",
                    previous_id=domain["id"],
                    change_kind="revise",
                )
                service.review_domain(updated["id"], "accept", "合成定义换版")
            else:
                add("a", "Java 新正文")
            continuation = DomainToolModel(job)
            with pytest.raises(ProbeError, match="RESEARCH_KNOWLEDGE_CHANGED_RESTART"):
                await research(
                    repository,
                    "Python 任务",
                    Settings(),
                    model=continuation,
                    checkpoint=(store, run["id"]),
                    resume=True,
                )
            assert continuation.calls == 0
            assert store.get(run["id"])["result"]["stale_knowledge"]

        asyncio.run(scenario())
    finally:
        store.close()


def test_domain_knowledge_query_limits_cover_full_match_count_before_truncation(corpus):
    repository, add, _ = corpus
    job = add("a")
    for index in range(7):
        domain = active_domain(repository, "domain_" + str(index))
        reviewed_relation(repository, domain, job)
        reviewed_relation(repository, domain, job)
    result = DomainKnowledgeService(repository).browse_for_research(
        ["Python"], job_ids=[job], public_document_ids=[]
    )
    assert result["matching_relations"] == 14 and result["truncated"]
    assert len(result["domains"]) <= 6 and len(result["relations"]) <= 10


def test_domain_agent_rechecks_dependencies_after_model_call_before_executing_output(corpus):
    repository, add, _ = corpus
    job = add("a")
    domain = active_domain(repository)
    relation = reviewed_relation(repository, domain, job)

    class ChangesDuringCall(DomainToolModel):
        async def turn(self, history):
            output = await super().turn(history)
            if self.calls == 3:
                DomainKnowledgeService(repository).review_relation(
                    relation["id"], "withdraw", "合成模型等待期间知识发生变化"
                )
            return output

    result = asyncio.run(
        research(
            repository,
            "Python 任务",
            Settings(),
            job_ids=[job],
            model=ChangesDuringCall(job),
            max_calls=5,
        )
    )
    assert result["status"] == "failed"
    assert result["stop_reason"] == "RESEARCH_KNOWLEDGE_CHANGED_RESTART"
    assert result["model_calls"] == 3 and result["stale_knowledge"]
    assert not any(item["tool"] == "read_job" for item in result["trace"])
