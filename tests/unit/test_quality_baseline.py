"""隔离合成资料验证质量评测机制；不计为真实研究质量证明。"""

import json

import pytest

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality.service import (
    DIMENSIONS,
    freeze,
    load_corpus,
    lock_suite,
    paired_evaluation,
    review_research,
)
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def corpus(tmp_path):
    database = tmp_path / "source.db"
    upgrade(database)
    repository = Repository(database)
    try:
        ids = []
        for identity, text in (("one", "构建智能体，Python必备"), ("two", "Java服务，Docker加分")):
            ids.append(
                import_jd(
                    repository,
                    RawArchive(tmp_path / "raw"),
                    ManualJD(
                        title="模拟·质量评测",
                        company="模拟公司",
                        external_id=identity,
                        description=text,
                        data_kind="synthetic",
                    ),
                )["job_id"]
            )
    finally:
        repository.close()
    directory = tmp_path / "frozen"
    freeze(database, directory)
    return directory, ids


def cases(ids):
    return [
        {
            "id": "dev",
            "split": "development",
            "question": "哪个岗位建设Agent？",
            "terms": ["Agent"],
            "relevant": [{"job_id": ids[0], "quote": "构建智能体", "reason": "明确工作任务"}],
            "critical": True,
            "notes": "合成标签",
        },
        *[
            {
                "id": "holdout-" + str(index),
                "split": "holdout",
                "question": "哪个岗位建设Agent？",
                "terms": ["Agent"],
                "relevant": [{"job_id": ids[0], "quote": "构建智能体", "reason": "明确工作任务"}],
                "critical": True,
                "notes": "重复题只验证机制，不作真实验收",
            }
            for index in range(4)
        ],
    ]


def test_frozen_corpus_rejects_tampering_and_keeps_unknown_publication(corpus):
    directory, _ = corpus
    manifest = load_corpus(directory)
    assert manifest["detail_total"] == 2
    assert all(doc["source_published_at"] is None for doc in manifest["documents"])
    path = directory / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["documents"][0]["text"] = "伪造正文"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ProbeError, match="QUALITY_CORPUS_CHANGED"):
        load_corpus(directory)


def test_split_and_anchor_are_checked_before_suite_is_locked(corpus):
    directory, ids = corpus
    value = cases(ids)
    value[0]["relevant"][0]["quote"] = "正文没有这句话"
    with pytest.raises(ProbeError, match="QUALITY_LABEL_ANCHOR_INVALID"):
        lock_suite(directory, value)
    value = cases(ids)
    for case in value:
        case["split"] = "development"
    with pytest.raises(ProbeError, match="QUALITY_SEPARATE_HOLDOUT_REQUIRED"):
        lock_suite(directory, value)
    lock_suite(directory, cases(ids))
    with pytest.raises(FileExistsError):
        lock_suite(directory, cases(ids))


def test_real_retriever_pair_is_provisional_without_human_labels(corpus):
    directory, ids = corpus
    lock_suite(directory, cases(ids))
    aliases = {"Agent": ["智能体"]}
    dev = paired_evaluation(directory, aliases)
    assert dev["baseline_mean_recall"] == 0
    assert dev["candidate_mean_recall"] == 1
    assert dev["source_and_budget_guard"]
    assert dev["status"] == "insufficient"
    result = paired_evaluation(directory, aliases, phase="holdout")
    assert result["status"] == "insufficient"
    assert result["label_review_status"] == "pending_human"
    with pytest.raises(ProbeError, match="QUALITY_HOLDOUT_ALREADY_USED"):
        paired_evaluation(directory, aliases, phase="holdout")


def test_holdout_requires_candidate_lock_and_human_review_does_not_activate(corpus):
    directory, ids = corpus
    lock_suite(directory, cases(ids), label_origin="human", reviewer="隔离测试审核者")
    aliases = {"Agent": ["智能体"]}
    with pytest.raises(ProbeError, match="QUALITY_CANDIDATE_MUST_BE_LOCKED"):
        paired_evaluation(directory, aliases, phase="holdout")
    paired_evaluation(directory, aliases)
    result = paired_evaluation(directory, aliases, phase="holdout")
    assert result["status"] == "accepted_for_human_review"
    assert "未启用" in result["activation"]
    assert result["external_calls"] == 0


def test_semantic_review_requires_each_claim_and_exact_frozen_source(corpus):
    directory, ids = corpus
    lock_suite(directory, cases(ids))
    paired = paired_evaluation(directory, {"Agent": ["智能体"]})
    evidence = paired["cases"][0]["candidate"]["evidence"]
    result = {
        "status": "completed",
        "claims": [{"text": "建设智能体", "evidence_ids": [evidence[0]["id"]]}],
        "evidence": evidence,
    }
    judgments = {
        dimension: {"rating": "pass", "reason": "隔离测试审核", "claim_indexes": [0]}
        for dimension in DIMENSIONS
    }
    review = review_research(directory, "dev", result, judgments, reviewer="隔离测试审核者")
    assert review["status"] == "reviewed_pass"
    assert review["usage"]["cost"] is None
    agent_review = review_research(
        directory, "dev", result, judgments, reviewer="测试Agent", reviewer_kind="agent_assisted"
    )
    assert agent_review["status"] == "needs_attention"
    judgments["citation_semantics"]["claim_indexes"] = []
    with pytest.raises(ProbeError, match="QUALITY_ALL_CLAIMS_REQUIRE_SEMANTIC_REVIEW"):
        review_research(directory, "dev", result, judgments, reviewer="隔离测试审核者")
    judgments["citation_semantics"]["claim_indexes"] = [0]
    result["evidence"][0]["quote"] = "伪造引用"
    review = review_research(directory, "dev", result, judgments, reviewer="隔离测试审核者")
    assert review["status"] == "needs_attention"
    assert not review["source_scope_guard"]
