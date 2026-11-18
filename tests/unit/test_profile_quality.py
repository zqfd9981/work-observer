"""完整画像审核的隔离业务回归；合成人审动作不冒充实际人类验收。"""

import asyncio
import json
from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from work_observer.analysis.profiles import ProfileService
from work_observer.api.profile_quality import ProfileQualityReviewInput
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.dependencies import DependencyAudit
from work_observer.memory.service import MemoryService
from work_observer.quality.profile_reviews import ProfileQualityReviewService
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS, digest
from work_observer.reports.inbox import InboxService
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import JobAnalysis
from work_observer.storage.repository import Repository


class ProfileModel:
    def __init__(self, job_id, evidence_id):
        self.job_id, self.evidence_id, self.calls = job_id, evidence_id, 0

    async def turn(self, history):
        self.calls += 1
        if self.calls == 1:
            name, arguments = "query_jobs", {}
        elif self.calls == 2:
            name, arguments = "read_job", {"job_id": self.job_id}
        elif self.calls == 3:
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": category,
                            "basis": "direct",
                            "requirement": requirement,
                            "text": text,
                            "evidence_ids": [self.evidence_id],
                        }
                        for category, requirement, text in (
                            ("business", "unspecified", "面向客户服务"),
                            ("task", "unspecified", "开发 RAG 应用"),
                            ("deliverable", "unspecified", "交付服务接口"),
                            ("responsibility", "unspecified", "负责上线维护"),
                            ("ability", "required", "必备 Python"),
                            ("tool", "preferred", "Docker 加分"),
                        )
                    ],
                    "gaps": ["验收方式待核实"],
                },
            )
        else:
            name, arguments = (
                "finish_profile",
                {
                    "domains": [
                        {
                            "domain": "business_application",
                            "rationale": "明确开发业务应用并交付接口",
                            "evidence_ids": [self.evidence_id],
                        }
                    ],
                    "interview_questions": [
                        "想向招聘方确认，接口和上线维护如何验收？",
                        "想向招聘方了解，Python资格条件如何考核？",
                    ],
                },
            )
        call = {
            "type": "function_call",
            "call_id": str(self.calls),
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
        return [call], call


@pytest.fixture
def profile_quality(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    job = import_jd(
        repo,
        RawArchive(tmp_path / "raw", []),
        ManualJD(
            title="合成画像岗位",
            company="合成公司",
            external_id="a",
            description="业务为客户服务；职责：开发 RAG 应用并交付服务接口，负责上线维护。"
            "必备 Python；加分 Docker。",
            data_kind="synthetic",
        ),
    )["job_id"]
    store = ResearchStore(tmp_path / "custom-checkpoints.db", str(path.resolve()))
    repo.bind_research_store(store)
    personal = MemoryService(repo).create("preference", "合成明确偏好：RAG服务开发")
    profiles = ProfileService(repo)
    settings = Settings(model_name="synthetic-test")
    output = asyncio.run(
        profiles.analyze(
            job, settings, model=ProfileModel(job, Catalog(repo).evidence(job)[0]["id"])
        )
    )
    yield (
        ProfileQualityReviewService(store, repo),
        profiles,
        repo,
        store,
        output,
        personal,
        settings,
    )
    store.close()
    repo.close()


def complete_review(packet, **updates):
    value = {
        "artifact_sha256": packet["artifact_sha256"],
        "reviewer": "合成机制审核者",
        "reviewer_kind": "human",
        "decision": "pending",
        "note": "合成逐项核对，不是真实人类标签",
        "dimensions": {key: {"rating": "pass", "reason": "合成已对照原文"} for key in DIMENSIONS},
        "claim_reviews": [
            {
                "index": row["index"],
                "support": "supported",
                "requirement": "correct",
                "note": "合成逐条语义核对",
            }
            for row in packet["claims"]
        ],
        "domain_reviews": [
            {
                "index": row["index"],
                "support": "supported",
                "scope": "correct",
                "note": "合成领域与实际任务对照",
            }
            for row in packet["domains"]
        ],
        "question_reviews": [
            {
                "index": row["index"],
                "direction": "correct",
                "relevance": "correct",
                "note": "合成面向招聘方核实实际缺口",
            }
            for row in packet["interview_questions"]
        ],
    }
    value.update(updates)
    return ProfileQualityReviewInput.model_validate(value).model_dump()


def test_packet_binds_full_raw_result_including_supplement_and_reads_complete_sources(
    profile_quality,
):
    service, _, repo, store, output, _, _ = profile_quality
    packet = service.packet(output["id"])
    with Session(repo.engine) as session:
        raw = deepcopy(session.get(JobAnalysis, output["id"]).result)
    base = store.get(raw["run_id"])["result"]
    assert "domains" not in base and "interview_questions" not in base
    assert packet["artifact_sha256"] == digest(raw) != digest(base)
    assert packet["approve_allowed"] and len(packet["claims"]) == 6
    assert packet["data_kind"] == "synthetic"
    assert service.overview()["profiles"][0]["data_kind"] == "synthetic"
    assert len(packet["domains"]) == 1 and len(packet["interview_questions"]) == 2
    assert (
        packet["source_texts"][0]["text"]
        == repo.job(output["job_id"])["current"]["description_text"]
    )
    assert packet["domains"][0]["citations"][0]["valid"]


def test_supplement_hash_change_makes_old_review_stale_without_rebinding(profile_quality):
    service, _, repo, _, output, _, _ = profile_quality
    packet = service.packet(output["id"])
    old = service.submit(output["id"], complete_review(packet))
    with Session(repo.engine) as session, session.begin():
        row = session.get(JobAnalysis, output["id"])
        changed = deepcopy(row.result)
        changed["interview_questions"][0] = "改变后的核实问题"
        row.result = changed
    current = service.packet(output["id"])
    assert current["artifact_sha256"] != packet["artifact_sha256"]
    assert current["claims"] == packet["claims"]
    assert current["reviews"][0]["id"] == old["id"] and current["reviews"][0]["stale_artifact"]
    with pytest.raises(ProbeError, match="PROFILE_QUALITY_ARTIFACT_CHANGED_REFRESH"):
        service.submit(output["id"], complete_review(packet, decision="approve"))


def test_blind_packet_is_current_full_artifact_without_prior_reviews_or_source_run_id(
    profile_quality,
):
    service, _, _, _, output, _, _ = profile_quality
    packet = service.packet(output["id"])
    service.submit(
        output["id"],
        complete_review(packet, reviewer="SYNTHETIC_OLD_REVIEWER", note="SYNTHETIC_OLD_SCORE"),
    )
    blind = service.blind_packet(output["id"])
    encoded = json.dumps(blind)
    assert blind["artifact_sha256"] == packet["artifact_sha256"]
    assert blind["data_kind"] == "synthetic"
    assert len(blind["result"]["domains"]) == len(packet["domains"])
    assert len(blind["result"]["interview_questions"]) == len(packet["interview_questions"])
    assert all(
        value not in encoded
        for value in (
            "SYNTHETIC_OLD_REVIEWER",
            "SYNTHETIC_OLD_SCORE",
            packet["source_run_id"],
            output["id"],
        )
    )
    assert blind["result"]["claims"][0]["citations"][0]["source"] == "S1"


def test_every_supplement_item_and_known_semantics_required_before_approval(profile_quality):
    service, _, _, _, output, _, _ = profile_quality
    packet = service.packet(output["id"])
    for field, code in (
        ("domain_reviews", "PROFILE_QUALITY_ALL_DOMAINS_REQUIRED"),
        ("question_reviews", "PROFILE_QUALITY_ALL_QUESTIONS_REQUIRED"),
        ("claim_reviews", "PROFILE_QUALITY_ALL_CLAIMS_REQUIRED"),
    ):
        with pytest.raises(ProbeError, match=code):
            service.submit(output["id"], complete_review(packet, **{field: []}, decision="approve"))
    for field, key in (
        ("claim_reviews", "support"),
        ("domain_reviews", "scope"),
        ("question_reviews", "direction"),
    ):
        review = complete_review(packet, decision="approve")
        review[field][0][key] = "unknown"
        with pytest.raises(
            ProbeError, match="PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW"
        ):
            service.submit(output["id"], review)
    review = complete_review(packet, decision="approve")
    review["dimensions"]["profile_coverage"]["rating"] = "unknown"
    with pytest.raises(ProbeError, match="PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW"):
        service.submit(output["id"], review)
    accepted = service.submit(output["id"], complete_review(packet, decision="approve"))
    assert accepted["status"] == "approved"


def test_task_only_source_can_be_honestly_unknown_but_not_unreviewed_or_partial(
    profile_quality, tmp_path
):
    service, profiles, repo, _, _, _, settings = profile_quality

    class TaskOnlyModel(ProfileModel):
        def __init__(self, job_id, evidence_id, *, partial=False):
            super().__init__(job_id, evidence_id)
            self.partial = partial

        async def turn(self, history):
            output, call = await super().turn(history)
            if self.calls == 3:
                arguments = {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "整理资料并维护目录",
                            "evidence_ids": [self.evidence_id],
                        }
                    ],
                    "gaps": ["原文仅披露任务，业务、交付物、责任、能力与工具均未披露"],
                }
                call["arguments"] = json.dumps(arguments, ensure_ascii=False)
            elif self.calls == 4:
                call["name"] = "invalid_supplement" if self.partial else "finish_profile"
                call["arguments"] = json.dumps(
                    {
                        "domains": [],
                        "interview_questions": [
                            "想向招聘方确认，该岗位的业务归属、交付验收、个人责任及资格工具要求是什么？"
                        ],
                    },
                    ensure_ascii=False,
                )
            return output, call

    for partial in (False, True):
        job = import_jd(
            repo,
            RawArchive(tmp_path / "task-only-raw", []),
            ManualJD(
                title="仅披露任务的合成岗位",
                company="合成公司",
                external_id=f"task-only-{partial}",
                description="工作任务：整理资料并维护目录。",
                data_kind="synthetic",
            ),
        )["job_id"]
        output = asyncio.run(
            profiles.analyze(
                job,
                settings,
                model=TaskOnlyModel(job, Catalog(repo).evidence(job)[0]["id"], partial=partial),
            )
        )
        packet = service.packet(output["id"])
        assert packet["source_eligibility"]["eligible"]
        assert set(packet["missing_dimensions"]) == {
            "business",
            "deliverable",
            "responsibility",
            "ability",
            "tool",
        }
        assert packet["complete_artifact"] is not partial
        assert packet["approve_allowed"] is not partial
        review = complete_review(packet, decision="approve")
        for key in ("profile_coverage", "unknown_handling", "question_answered"):
            review["dimensions"][key]["reason"] = (
                "合成human actor已核对全文：仅任务有披露，其余五类是原文未知而非模型漏读；"
                "画像不外推岗位优劣，问题面向招聘方澄清未知。此动作不是真实人类验收。"
            )
        if partial:
            assert packet["artifact_status"] == "partial"
            with pytest.raises(
                ProbeError, match="PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW"
            ):
                service.submit(output["id"], review)
        else:
            for key in ("profile_coverage", "unknown_handling", "question_answered"):
                unreviewed = deepcopy(review)
                unreviewed["dimensions"][key]["rating"] = "unknown"
                with pytest.raises(
                    ProbeError, match="PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW"
                ):
                    service.submit(output["id"], unreviewed)
            assert service.submit(output["id"], review)["status"] == "approved"


def test_agent_feedback_cannot_approve_or_poison_cache_and_human_reject_does_not_reject_base(
    profile_quality,
):
    service, profiles, repo, store, output, _, settings = profile_quality
    packet = service.packet(output["id"])
    with pytest.raises(ProbeError, match="PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW"):
        service.submit(
            output["id"],
            complete_review(packet, reviewer_kind="agent_assisted", decision="approve"),
        )
    service.submit(
        output["id"], complete_review(packet, reviewer_kind="agent_assisted", decision="reject")
    )
    assert not profiles.get(output["job_id"])["stale"]
    base_before = store.get(packet["source_run_id"])
    model = ProfileModel(output["job_id"], Catalog(repo).evidence(output["job_id"])[0]["id"])
    cached = asyncio.run(profiles.analyze(output["job_id"], settings, model=model))
    assert cached["id"] == output["id"] and cached["cached"] and model.calls == 0
    service.submit(output["id"], complete_review(packet, decision="reject"))
    stale = profiles.get(output["job_id"])
    assert stale["stale"] and stale["profile_quality_review"]["status"] == "rejected"
    assert store.get(packet["source_run_id"]) == base_before
    assert DependencyAudit(repo).run(packet["source_run_id"])["eligible"]
    assert QualityReviewService(store, repo).packet(packet["source_run_id"])["approve_allowed"]


def test_human_rejected_cache_is_recomputed_with_new_id_and_old_artifact_preserved(profile_quality):
    service, profiles, repo, store, output, _, settings = profile_quality
    packet = service.packet(output["id"])
    service.submit(output["id"], complete_review(packet, decision="reject"))
    model = ProfileModel(output["job_id"], Catalog(repo).evidence(output["job_id"])[0]["id"])
    fresh = asyncio.run(profiles.analyze(output["job_id"], settings, model=model))
    assert fresh["id"] != output["id"] and not fresh["cached"] and model.calls == 4
    with Session(repo.engine) as session:
        old = session.get(JobAnalysis, output["id"])
        new = session.get(JobAnalysis, fresh["id"])
        assert digest(old.result) == packet["artifact_sha256"]
        assert new.cache_key.startswith(old.cache_key + ":")
    assert not fresh["stale"] and fresh["profile_quality_review"]["status"] == "pending"
    assert store.get(packet["source_run_id"])["state"] == "finished"


def test_partial_missing_source_and_changed_preference_cannot_approve(profile_quality):
    service, profiles, repo, _, output, personal, _ = profile_quality
    before = service.packet(output["id"])
    MemoryService(repo).revise(personal["id"], "改为合成新偏好")
    current = service.packet(output["id"])
    assert current["artifact_sha256"] == before["artifact_sha256"]
    assert current["stale"] and not current["approve_allowed"]
    with pytest.raises(ProbeError, match="PROFILE_QUALITY_APPROVAL_REQUIRES_COMPLETE_HUMAN_REVIEW"):
        service.submit(output["id"], complete_review(current, decision="approve"))
    with Session(repo.engine) as session, session.begin():
        row = session.get(JobAnalysis, output["id"])
        value = deepcopy(row.result)
        value["status"], value["run_id"] = "partial", "a" * 32
        row.status, row.result = "partial", value
    partial = service.packet(output["id"])
    assert not partial["approve_allowed"] and not partial["complete_artifact"]
    assert not partial["source_eligibility"]["eligible"]


def test_forgetting_after_analysis_deleted_erases_all_free_text_and_is_retry_safe(profile_quality):
    service, _, repo, store, output, personal, _ = profile_quality
    packet = service.packet(output["id"])
    marker = "SYNTHETIC_PRIVATE_PROFILE_REVIEW"
    data = complete_review(packet, reviewer_kind="agent_assisted", decision="reject", note=marker)
    for name in ("claim_reviews", "domain_reviews", "question_reviews"):
        for item in data[name]:
            item["note"] = marker
    row = service.submit(output["id"], data)
    original_job = repo.job(output["job_id"])
    forgotten = MemoryService(repo).forget(personal["id"])
    assert output["id"] in forgotten["deleted_profile_ids"]
    cleared = service.invalidate(memory_ids=[personal["id"]])
    assert cleared["invalidated_profile_quality_review_ids"] == [row["id"]]
    assert service.invalidate(memory_ids=[personal["id"]])[
        "invalidated_profile_quality_review_ids"
    ] == [row["id"]]
    with store.lock:
        encoded = store.db.execute(
            "SELECT record FROM profile_quality_reviews WHERE namespace=?", (store.namespace,)
        ).fetchone()[0]
        assert marker not in encoded and json.loads(encoded)["status"] == "invalidated"
    assert all(marker not in item["body"] for item in InboxService(repo).list())
    assert repo.job(output["job_id"]) == original_job
    with pytest.raises(ProbeError, match="PROFILE_QUALITY_ARTIFACT_NOT_FOUND"):
        service.packet(output["id"])
