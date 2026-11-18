"""研究语义送审的隔离机制测试；判断文字均为明确合成。"""

from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from work_observer.api.quality import QualityReviewInput
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.reports.inbox import InboxService
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import Job
from work_observer.storage.repository import Repository


@pytest.fixture
def reviews(tmp_path):
    database = tmp_path / "test.db"
    upgrade(database)
    repository = Repository(database)
    job = import_jd(
        repository,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成岗位",
            company="模拟公司",
            external_id="one",
            description="Python为必备，Docker加分",
            data_kind="synthetic",
        ),
    )["job_id"]
    evidence = Catalog(repository).evidence(job)
    store = ResearchStore(tmp_path / "checkpoints.db", str(database))
    run = store.create({"question": "合成题：Docker是必备吗？"})
    store.save(
        run["id"],
        state="completed",
        result={
            "status": "completed",
            "question": "合成题：Docker是必备吗？",
            "scope": {"jobs": [{"id": job}]},
            "evidence": evidence,
            "claims": [
                {
                    "text": "Docker为加分",
                    "requirement": "preferred",
                    "category": "tool",
                    "evidence_ids": [evidence[0]["id"]],
                }
            ],
            "gaps": ["来源未说明具体版本"],
            "model_calls": 2,
            "elapsed_seconds": 1.25,
        },
    )
    yield QualityReviewService(store, repository), run["id"], job
    store.close()
    repository.close()


def review_data(packet, **updates):
    value = {
        "result_sha256": packet["result_sha256"],
        "reviewer": "隔离测试审核者",
        "reviewer_kind": "human",
        "decision": "pending",
        "note": "合成核对待补查",
        "dimensions": {key: {"rating": "unknown", "reason": "需要核对"} for key in DIMENSIONS},
        "claim_reviews": [
            {
                "index": claim["index"],
                "support": "unknown",
                "requirement": "unknown",
                "note": "需要核对原文",
            }
            for claim in packet["claims"]
        ],
    }
    value.update(updates)
    return QualityReviewInput.model_validate(value).model_dump()


def test_packet_has_each_claim_source_and_pending_never_passes(reviews):
    service, identity, _ = reviews
    packet = service.packet(identity)
    assert packet["approve_allowed"]
    assert packet["claims"][0]["citations"][0]["quote"] == "Python为必备，Docker加分"
    assert packet["usage"]["cost"] is None
    pending = service.submit(identity, review_data(packet))
    assert pending["status"] == "pending"
    assert service.overview()["runs"][0]["review_status"] == "pending"
    value = review_data(packet, decision="approve")
    with pytest.raises(ProbeError, match="QUALITY_APPROVAL_REQUIRES_HUMAN"):
        service.submit(identity, value)


def test_approval_requires_human_all_claims_and_dimensions(reviews):
    service, identity, _ = reviews
    packet = service.packet(identity)
    value = review_data(packet, decision="approve")
    for dim in value["dimensions"].values():
        dim["rating"] = "pass"
    for claim in value["claim_reviews"]:
        claim.update(support="supported", requirement="correct")
    agent = {**value, "reviewer_kind": "agent_assisted"}
    with pytest.raises(ProbeError, match="QUALITY_APPROVAL_REQUIRES_HUMAN"):
        service.submit(identity, agent)
    missing = {**value, "claim_reviews": []}
    with pytest.raises(ProbeError, match="QUALITY_ALL_CLAIMS"):
        service.submit(identity, missing)
    saved = service.submit(identity, value)
    assert saved["status"] == "approved"
    assert service.submit(identity, value)["id"] == saved["id"]
    assert len(service.list_run(identity)) == 1


def test_rejection_creates_one_followup_and_restart_keeps_review(reviews):
    service, identity, _ = reviews
    data = review_data(
        service.packet(identity), decision="reject", note="需要补查合成岗位的原文性质"
    )
    saved = service.submit(identity, data)
    service.submit(identity, data)
    notes = InboxService(service.repository).list()
    assert len(notes) == 1
    assert notes[0]["related_id"] == identity
    assert notes[0]["body"] == data["note"]
    reopened = ResearchStore(service.store.path, service.store.namespace)
    try:
        assert (
            QualityReviewService(reopened, service.repository).list_run(identity)[0]["id"]
            == saved["id"]
        )
        other = ResearchStore(service.store.path, "other-database")
        try:
            assert QualityReviewService(other, service.repository).overview()["runs"] == []
        finally:
            other.close()
    finally:
        reopened.close()


def test_result_change_and_source_change_require_recheck(reviews):
    service, identity, job = reviews
    packet = service.packet(identity)
    data = review_data(packet)
    result = deepcopy(service.store.get(identity)["result"])
    result["claims"][0]["text"] = "修订后的合成判断"
    service.store.save(identity, result=result)
    with pytest.raises(ProbeError, match="QUALITY_RESULT_CHANGED"):
        service.submit(identity, data)
    with Session(service.repository.engine) as session, session.begin():
        session.get(Job, job).description_text = "新版本合成正文"
    assert not service.packet(identity)["approve_allowed"]
    assert service.overview()["runs"][0]["review_status"] == "needs_recheck"


def test_forgetting_erases_review_free_text_and_blocks_old_packet(reviews):
    service, identity, _ = reviews
    data = review_data(service.packet(identity), decision="reject", note="应忘记的合成个性化评语")
    service.submit(identity, data)
    service.store.invalidate_runs([identity])
    assert service.invalidate([identity])["invalidated_quality_review_ids"]
    with service.store.lock:
        raw = service.store.db.execute("select record from quality_reviews").fetchone()[0]
    assert "个性化" not in raw
    with pytest.raises(ProbeError, match="QUALITY_RESEARCH_FORGOTTEN"):
        service.packet(identity)
    with pytest.raises(ProbeError, match="QUALITY_RESEARCH_FORGOTTEN"):
        service.submit(identity, data)
