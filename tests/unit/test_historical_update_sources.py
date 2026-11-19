"""Historic source panels use acquisition/ingestion cutoffs, without inventing past analysis."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_domain_updates import updates as updates

from work_observer.collection.contracts import now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.models import JobObservation


def test_cutoff_reconstructs_old_job_and_archive_before_later_sources_and_analysis(
    updates, tmp_path
):
    service, add = updates
    repo = service.repository
    job = add("one", "Python接口开发", city="上海")
    docs = PublicDocumentService(repo, tmp_path / "materials")
    old = docs.archive_text("合成流程", "先人工复核", "合成资料")["document"]
    cutoff = now()
    add("one", "Java接口开发", city="北京")
    later_job = add("two", "Python后补岗位", city="上海")
    revised = docs.revise_text(old["id"], "合成流程", "须由平台负责人复核")["document"]
    # Backfilling an observation time cannot make a later ingestion known in the past.
    with Session(repo.engine) as session, session.begin():
        for observation in session.scalars(
            select(JobObservation).where(JobObservation.job_id == later_job)
        ):
            observation.observed_at = cutoff
    knowledge = DomainKnowledgeService(repo)
    domain = knowledge.propose_domain("later", "现在的工作类型", "今天才明确的分类")
    knowledge.review_domain(domain["id"], "accept", "合成核对")
    relation = knowledge.propose_relation(
        domain["id"], "task", "Java接口", "ability", "接口能力", Catalog(repo).evidence(job)
    )
    knowledge.review_relation(relation["id"], "accept", "合成核对")
    later_cutoff = now()
    # Create the newer source panel first: comparison order follows source cutoff, not save order.
    newer = service.capture("较晚来源", as_of=later_cutoff, terms=["Python"], include_archived=True)
    older = service.capture("较早来源", as_of=cutoff, terms=["Python"], include_archived=True)
    assert {row["job_id"] for row in older["jobs"]} == {job}
    assert older["jobs"][0]["fields"]["city"] == "上海"
    assert older["statistics"] == [dict(term="Python", literal_jobs=1, denominator=1)]
    assert [row["id"] for row in older["archived_scope"]["documents"]] == [old["id"]]
    assert [row["id"] for row in newer["archived_scope"]["documents"]] == [revised["id"]]
    assert older["definitions"] == newer["definitions"] == older["relations"] == []
    assert older["sample"]["missing_profiles"] is None
    assert all(row["profile"] is None and row["domain"] is None for row in older["jobs"])
    report = service.compare(older["id"], newer["id"])
    assert report["sample_changes"]["added_job_ids"] == [later_job]
    assert len(report["content_changes"]) == 1
    assert report["archived_changes"]["changes"][0]["change_kind"] == "user_text_revision"
    assert report["method_changes"]["analysis_comparable"] is False
    assert report["method_changes"]["domain_definitions_changed"] is None
    assert report["method_changes"]["profiles"] == report["method_changes"]["classifications"] == []
    assert report["observation_times"]["before"]["source_cutoff"] == cutoff
    prepared = service.followup(report["id"], "核实这两次来源差异")
    assert cutoff in prepared["question"] and later_cutoff in prepared["question"]
    assert "不能把现在的内容代替过去" in prepared["question"]
    assert service.list()["captures"][0]["as_of"] == cutoff
    with pytest.raises(ProbeError, match="UPDATE_CAPTURE_ORDER_INVALID"):
        service.compare(newer["id"], older["id"])
    current = service.capture("当前观察")
    assert current["analysis_observed"] and current["definitions"] and current["relations"]


def test_current_conditions_on_past_sources_stay_explicit_and_forgettable(updates, tmp_path):
    service, add = updates
    repo, store = service.repository, service.store
    repo.bind_research_store(store)
    add("one", city="上海")
    cutoff = now()
    memory = MemoryService(repo)
    private = memory.create("preference", "SYNTHETIC_CURRENT_PERSONAL_CONDITION")
    before = service.capture("回看一", as_of=cutoff, include_personal=True)
    after = service.capture("回看二", as_of=cutoff, include_personal=True)
    assert before["personal_basis"] == "current_explicit_conditions"
    assert before["personal"]["notes"][0]["content"] == private["content"]
    report = service.compare(before["id"], after["id"])
    assert "不还原当时个人偏好" in report["personal_impact"]["note"]
    forget_personal(repo, store, private["id"], tmp_path / "reports")
    with pytest.raises(ProbeError, match="UPDATE_MEMORY_FORGOTTEN"):
        service.report(report["id"])
    assert repo.counts()["jobs"] == 1


@pytest.mark.parametrize(
    "options,error",
    [
        ({"as_of": "2099-01-01T00:00:00+00:00"}, "UPDATE_CUTOFF_IN_FUTURE"),
        ({"as_of": "2026-01-01T00:00:00"}, "INVALID_RETRIEVAL_TIME"),
        (
            {"as_of": "2026-01-01T00:00:00+00:00", "domain_id": "current-domain"},
            "UPDATE_HISTORICAL_DOMAIN_UNAVAILABLE",
        ),
    ],
)
def test_invalid_or_unsupported_time_scope_does_not_create_a_panel(updates, options, error):
    service, add = updates
    add("one")
    with pytest.raises(ProbeError, match=error):
        service.capture("拒绝含糊历史口径", **options)
    assert not service.list()["captures"]
