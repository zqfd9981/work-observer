"""合成标签扮演人工动作验证有限试用机制；不是真实人类标注或市场效果。"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.maintenance import backup_workspace, file_sha, restore_workspace
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.quality.releases import LocalRetrievalTrialService
from work_observer.quality.service import digest, freeze, lock_suite, paired_evaluation
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import SourceDocument
from work_observer.storage.repository import Repository
from work_observer.tracking.evaluation import StrategyService


@pytest.fixture
def trial_data(tmp_path):
    database = tmp_path / "app.db"
    upgrade(database)
    repo = Repository(database)
    archive = RawArchive(tmp_path / "raw")

    def add(identity="one", text="构建智能体，资料解析，记忆存储，工具路由，评测数据。"):
        return import_jd(
            repo,
            archive,
            ManualJD(
                title="合成试用岗位",
                company="合成评测公司",
                external_id=identity,
                description=text,
                data_kind="synthetic",
            ),
        )["job_id"]

    job = add()
    other = add("two", "维护Java传统服务。")
    store = ResearchStore(tmp_path / "checkpoints.db", str(database))
    service = LocalRetrievalTrialService(store, repo)
    aliases = {
        "Agent": ["智能体"],
        "文档处理": ["资料解析"],
        "Memory": ["记忆存储"],
        "Tool routing": ["工具路由"],
        "Evaluation": ["评测数据"],
    }

    def bundle(*, origin="human", independent=True):
        identity = uuid4().hex
        directory = service.artifact_root / identity
        freeze(database, directory)
        cases = []
        for index, (term, anchor) in enumerate(
            (
                ("Agent", "构建智能体"),
                ("文档处理", "资料解析"),
                ("Memory", "记忆存储"),
                ("Tool routing", "工具路由"),
                ("Evaluation", "评测数据"),
            )
        ):
            cases.append(
                {
                    "id": str(index),
                    "split": "development" if index == 0 else "holdout",
                    "question": "合成任务：检索" + term,
                    "terms": [term],
                    "relevant": [
                        {"job_id": job, "quote": anchor, "reason": "合成金标，仅用于机制测试"}
                    ],
                    "critical": True,
                    "notes": "合成actor扮演人工动作，不是真实人工标注。",
                }
            )
        lock_suite(
            directory,
            cases,
            label_origin=origin,
            reviewer="synthetic-human-fixture-actor",
            independent_labels=independent,
        )
        paired_evaluation(directory, aliases)
        report = paired_evaluation(directory, aliases, phase="holdout")
        return identity, directory, report

    yield service, job, other, add, bundle
    store.close()
    repo.close()


def activate(service, bundle_id, job, **kwargs):
    trial = service.shadow(bundle_id, [job], ["Agent"], **kwargs)
    assert trial["state"] == "awaiting_review"
    approved = service.review(
        trial["id"],
        "合成测试审核actor",
        "approve",
        "合成机制审核，非真实人审效果",
        labels_independent_confirmed=True,
    )
    assert approved["state"] == "active"
    return trial["id"]


def test_shadow_then_human_only_trial_is_bounded_and_default_never_changes(trial_data):
    service, job, other, add, bundle = trial_data
    identity, _, _ = bundle()
    before = StrategyService(service.repository).active_config()
    trial = service.shadow(identity, [job], ["Agent"], max_uses=1)
    assert trial["data_mode"] == "synthetic"
    assert trial["state"] == "awaiting_review"
    shadow = service.search(trial["id"], ["Agent"], request_key="before-human")
    assert shadow["mode"] == "baseline"
    assert shadow["retrieval"]["evidence"] == []
    with pytest.raises(ProbeError, match="TRIAL_INDEPENDENT_HUMAN_APPROVAL_REQUIRED"):
        service.review(
            trial["id"],
            "合成Agent",
            "approve",
            "不能冒充人审",
            reviewer_kind="agent_assisted",
            labels_independent_confirmed=True,
        )
    service.review(
        trial["id"], "合成actor", "approve", "明确局部合成试用", labels_independent_confirmed=True
    )
    result = service.search(trial["id"], ["Agent"], request_key="one")
    assert result["mode"] == "limited_candidate"
    assert result["uses"] == 1
    assert {row["job_id"] for row in result["retrieval"]["evidence"]} == {job}
    assert service.search(trial["id"], ["Agent"], request_key="one")["replayed"]
    fallback = service.search(trial["id"], ["Agent"], request_key="two")
    assert fallback["mode"] == "baseline"
    assert fallback["stop_reason"] == "use_budget_exhausted"
    assert StrategyService(service.repository).active_config() == before
    assert not RetrievalService(service.repository).search(["Agent"])["evidence"]


@pytest.mark.parametrize("origin,independent", [("agent_assisted", False), ("human", False)])
def test_agent_or_nonindependent_labels_cannot_activate(trial_data, origin, independent):
    service, job, _, _, bundle = trial_data
    identity, _, _ = bundle(origin=origin, independent=independent)
    trial = service.shadow(identity, [job], ["Agent"])
    assert trial["state"] == "insufficient"
    with pytest.raises(ProbeError, match="TRIAL_REAL_LABELS_OR_EVALUATION_INSUFFICIENT"):
        service.review(
            trial["id"],
            "合成actor",
            "approve",
            "即使点击仍不放行",
            labels_independent_confirmed=True,
        )
    assert service.search(trial["id"], ["Agent"], request_key="blocked")["mode"] == "baseline"


def test_live_sample_drift_and_expiry_automatically_revert(trial_data):
    service, job, _, add, bundle = trial_data
    identity, _, _ = bundle()
    trial = activate(service, identity, job)
    add(text="已变更为Java普通服务。")
    drift = service.search(trial, ["Agent"], request_key="changed")
    assert drift["mode"] == "baseline"
    assert drift["stop_reason"] == "local_sample_drift"
    # 新原文没有开发题相关证据，不能再借旧评测放行。
    with pytest.raises(ProbeError, match="QUALITY_LABEL_ANCHOR_INVALID"):
        bundle()


def test_expired_trial_and_file_change_cannot_be_reactivated(trial_data):
    service, job, _, _, bundle = trial_data
    identity, directory, _ = bundle()
    trial = activate(service, identity, job)
    with service.store.lock, service.store.db:
        row = service._get(trial)
        row["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        service._save(row, "synthetic_expiry_fixture")
    result = service.search(trial, ["Agent"], request_key="expired")
    assert result["mode"] == "baseline" and result["trial_state"] == "expired"
    with pytest.raises(ProbeError, match="TRIAL_CLOSED_NEW_SHADOW_REQUIRED"):
        service.review(
            trial, "actor", "approve", "关闭后不能重置预算", labels_independent_confirmed=True
        )
    second = activate(service, identity, job)
    path = directory / "holdout-result.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["candidate_aliases"] = {"Agent": ["Java"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    failed = service.search(second, ["Agent"], request_key="tampered")
    assert failed["mode"] == "baseline"
    assert failed["trial_state"] == "rolled_back"


def test_quality_failure_feedback_rolls_back_and_cannot_replay_old_candidate(trial_data):
    service, job, _, _, bundle = trial_data
    identity, _, _ = bundle()
    trial = activate(service, identity, job)
    service.search(trial, ["Agent"], request_key="reviewed-query")
    service.feedback(trial, "reviewed-query", "fail", "合成actor发现不相关结果")
    reverted = service.search(trial, ["Agent"], request_key="reviewed-query")
    assert reverted["mode"] == "baseline"
    assert reverted["stop_reason"] == "quality_feedback_failed"
    assert any(event["action"] == "automatic_rollback" for event in service.events(trial))


def test_query_and_scope_cannot_escape_approved_range(trial_data):
    service, job, other, _, bundle = trial_data
    identity, _, _ = bundle()
    trial = activate(service, identity, job)
    result = service.search(trial, ["Agent"], job_ids=[other], request_key="expanded")
    assert result["mode"] == "baseline" and result["stop_reason"] == "request_scope_drift"
    assert result["retrieval"]["evidence"] == []
    second = activate(service, identity, job)
    assert (
        service.search(second, ["任意新任务"], request_key="new-query")["stop_reason"]
        == "unreviewed_query"
    )
    public = json.dumps(service.bundles(), ensure_ascii=False)
    assert "holdout" not in public.replace("holdout_status", "").replace(
        "holdout_result_sha256", ""
    ).replace("holdout_attempt_sha256", "")
    assert "合成任务：检索Memory" not in public


def test_candidate_forged_quote_or_missing_baseline_coverage_reverts(trial_data, monkeypatch):
    service, job, _, _, bundle = trial_data
    identity, _, _ = bundle()
    trial = activate(service, identity, job)
    original = RetrievalService.search

    def corrupt(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self.alias_groups and result["evidence"]:
            result["evidence"][0]["quote"] = "合成伪造引用"
        return result

    monkeypatch.setattr(RetrievalService, "search", corrupt)
    result = service.search(trial, ["Agent"], request_key="corrupt")
    assert result["mode"] == "baseline"
    assert result["stop_reason"] == "candidate_evidence_or_coverage_guard_failed"


def test_missing_original_archive_closes_baseline_instead_of_returning_unverified_quote(trial_data):
    service, job, _, add, bundle = trial_data
    add(text="Agent构建智能体，资料解析，记忆存储，工具路由，评测数据。")
    identity, _, _ = bundle()
    trial = activate(service, identity, job)
    assert RetrievalService(service.repository).search(["Agent"], job_ids=[job])["evidence"]
    with Session(service.repository.engine) as session:
        path = session.scalar(
            select(SourceDocument.path).where(
                SourceDocument.id == service._sample([job])[0]["document_id"]
            )
        )
    Path(path).write_bytes(b"explicit synthetic corruption")
    result = service.search(trial, ["Agent"], request_key="missing-source")
    assert result["mode"] == "source_unavailable"
    assert result["retrieval"]["evidence"] == []
    assert result["retrieval"]["matching_jobs"] is None
    assert result["retrieval"]["sample"]["denominator"] is None


def test_forged_aggregate_is_not_enough_for_human_activation(trial_data):
    service, job, _, _, bundle = trial_data
    identity, directory, _ = bundle()
    path = directory / "holdout-result.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["candidate_mean_recall"] = 0.99
    path.write_text(json.dumps(raw), encoding="utf-8")
    trial = service.shadow(identity, [job], ["Agent"])
    assert trial["state"] == "insufficient"
    assert not trial["holdout_verified"]


def test_restart_keeps_budget_and_forget_erases_review_and_query_events(trial_data):
    service, job, _, _, bundle = trial_data
    memory = MemoryService(service.repository).create("preference", "合成试用关注点")
    run = service.store.create({"question": "合成关联研究"})
    service.store.save(
        run["id"],
        state="finished",
        result={
            "status": "completed",
            "scope": {"jobs": [{"id": job}]},
            "memory_used": [{"id": memory["id"], "version": memory["version"]}],
        },
    )
    identity, _, _ = bundle()
    trial = activate(service, identity, job, source_run_id=run["id"])
    service.search(trial, ["Agent"], request_key="persisted")
    reopened = ResearchStore(service.store.path, service.store.namespace)
    try:
        other = LocalRetrievalTrialService(reopened, service.repository)
        assert other.get(trial)["uses"] == 1
        service.store.invalidate_runs([run["id"]])
        invalidated = other.invalidate_research([run["id"]], [memory["id"]])
        assert invalidated["invalidated_retrieval_trial_ids"] == [trial]
        assert other.invalidate_research([run["id"]])["invalidated_retrieval_trial_ids"] == [trial]
        assert other.events(trial) == []
        assert "明确局部合成试用" not in str(other.get(trial))
        with pytest.raises(ProbeError, match="TRIAL_SOURCE_RESEARCH_FORGOTTEN"):
            other.search(trial, ["Agent"], request_key="persisted")
    finally:
        reopened.close()


def test_personal_forget_full_closure_scrubs_real_trial_records_and_feedback(trial_data):
    service, job, _, _, bundle = trial_data
    preference = MemoryService(service.repository).create("preference", "合成明确个人目标")
    run = service.store.create({"question": "合成关联研究"})
    service.store.save(
        run["id"],
        state="finished",
        result={
            "status": "completed",
            "scope": {"jobs": [{"id": job}]},
            "memory_used": [{"id": preference["id"], "version": preference["version"]}],
            "claims": [],
            "evidence": [],
        },
    )
    identity, _, _ = bundle()
    trial = activate(service, identity, job, source_run_id=run["id"])
    service.search(trial, ["Agent"], request_key="full-forget")
    service.feedback(trial, "full-forget", "pass", "synthetic private feedback text")
    forgotten = forget_personal(
        service.repository,
        service.store,
        preference["id"],
        Path(service.repository.engine.url.database).parent / "reports",
    )
    assert trial in forgotten["invalidated_retrieval_trial_ids"]
    assert service.get(trial)["state"] == "invalidated"
    assert service.events(trial) == []
    with service.store.lock:
        raw = service.store.db.execute("select record from retrieval_trials").fetchone()[0]
        assert "合成测试审核actor" not in raw
        assert "synthetic private feedback text" not in raw
    assert service.repository.counts()["jobs"] == 2


def test_fixed_bundle_backup_restore_keeps_bytes_budget_and_works_without_original_paths(
    trial_data,
):
    service, job, _, _, bundle = trial_data
    identity, directory, _ = bundle()
    (directory / ".env").write_text("SYNTHETIC_NOT_A_KEY", encoding="utf-8")
    (directory / "unexpected.py").write_text("not an artifact", encoding="utf-8")
    trial = activate(service, identity, job, max_uses=2)
    service.search(trial, ["Agent"], request_key="before-backup")
    root = Path(service.repository.engine.url.database).parent
    destination = root / "backup"
    original_sha = file_sha(directory / "corpus.db")
    backup_workspace(Path(service.repository.engine.url.database), destination, root / "reports")
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trial_bundles"] == [identity]
    assert not any(name.endswith((".env", ".py", "-wal", "-shm")) for name in manifest["files"])
    # 只移动测试创建的两个目录，验证恢复不借用原始路径。
    for name in ("raw", "quality-trials"):
        source = (root / name).resolve()
        target = (root / (name + "-unavailable")).resolve()
        assert source.is_relative_to(root.resolve()) and target.is_relative_to(root.resolve())
        source.rename(target)
    restored = root / "restored"
    result = restore_workspace(destination, restored)
    assert result["restored_trial_bundles"] == 1
    assert file_sha(restored / "quality-trials" / identity / "corpus.db") == original_sha
    repo = Repository(restored / "app.db")
    store = ResearchStore(restored / "checkpoints.db", str((restored / "app.db").resolve()))
    try:
        live = LocalRetrievalTrialService(store, repo)
        assert live.get(trial)["state"] == "active"
        assert live.get(trial)["uses"] == 1
        assert live.search(trial, ["Agent"], request_key="after-restore")["uses"] == 2
        assert live.search(trial, ["Agent"], request_key="exhausted")["mode"] == "baseline"
    finally:
        store.close()
        repo.close()


def test_restore_rejects_frozen_bundle_tamper_even_if_outer_file_hash_is_updated(trial_data):
    service, _, _, _, bundle = trial_data
    identity, _, _ = bundle()
    root = Path(service.repository.engine.url.database).parent
    destination = root / "backup"
    backup_workspace(Path(service.repository.engine.url.database), destination, root / "reports")
    relative = "quality-trials/" + identity + "/suite.json"
    path = destination / relative
    suite = json.loads(path.read_text(encoding="utf-8"))
    suite["label_origin"] = "forged"
    path.write_text(json.dumps(suite), encoding="utf-8")
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][relative] = file_sha(path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProbeError, match="QUALITY_SUITE_CHANGED"):
        restore_workspace(destination, root / "must-not-create")
    assert not (root / "must-not-create").exists()


def test_superseded_preference_through_active_knowledge_stops_trial(trial_data):
    service, job, _, _, bundle = trial_data
    memory = MemoryService(service.repository)
    preference = memory.create("preference", "合成呈现偏好一")
    evidence = Catalog(service.repository).evidence(job)

    def source(ref):
        run = service.store.create({"question": "合成带依赖研究"})
        service.store.save(
            run["id"],
            state="finished",
            result={
                "status": "completed",
                "scope": {"jobs": [{"id": job}]},
                "evidence": evidence,
                "claims": [],
                "memory_used": [{"id": ref["id"], "version": ref["version"]}],
            },
        )
        return run["id"]

    first = source(preference)
    knowledge = memory.create(
        "knowledge", "合成岗位构建智能体", evidence=evidence, source_run_id=first
    )
    knowledge = memory.activate(knowledge["id"])
    second = source(knowledge)
    identity, _, _ = bundle()
    trial = activate(service, identity, job, source_run_id=second)
    memory.revise(preference["id"], "合成呈现偏好二")
    assert next(row for row in memory.list() if row["id"] == knowledge["id"])["status"] == "active"
    result = service.search(trial, ["Agent"], request_key="dependency-changed")
    assert result["mode"] == "baseline"
    assert result["stop_reason"] == "upstream_dependency_changed"


def test_freeze_only_draft_can_backup_restore_without_becoming_activatable(trial_data):
    service, job, _, _, _ = trial_data
    root = Path(service.repository.engine.url.database).parent
    identity = uuid4().hex
    draft = service.artifact_root / identity
    freeze(Path(service.repository.engine.url.database), draft)
    original = {path.name: file_sha(path) for path in draft.iterdir()}
    backup_workspace(
        Path(service.repository.engine.url.database), root / "backup", root / "reports"
    )
    manifest = json.loads((root / "backup" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trial_bundle_stages"] == {identity: "frozen_draft"}
    restored = root / "restored"
    result = restore_workspace(root / "backup", restored)
    assert result["restored_trial_bundle_stages"] == {identity: "frozen_draft"}
    assert {
        path.name: file_sha(path) for path in (restored / "quality-trials" / identity).iterdir()
    } == original
    repo = Repository(restored / "app.db")
    store = ResearchStore(restored / "checkpoints.db", str((restored / "app.db").resolve()))
    try:
        live = LocalRetrievalTrialService(store, repo)
        assert live.bundles() == [{"id": identity, "state": "invalid_bundle"}]
        with pytest.raises(ProbeError, match="TRIAL_BUNDLE_DRAFT_NOT_EVALUATED"):
            live.shadow(identity, [job], ["Agent"])
        assert live.list() == []
    finally:
        store.close()
        repo.close()


@pytest.mark.parametrize("stage", ["labeled_draft", "evaluation_draft"])
def test_labeled_or_evaluation_draft_retains_stage_and_verifies_suite(trial_data, stage):
    service, _, _, _, bundle = trial_data
    identity, directory, _ = bundle()
    # 模拟评测已有attempt、结果尚未写出；保留候选锁与suite原字节。
    (directory / "holdout-result.json").unlink()
    if stage == "labeled_draft":
        (directory / "holdout-attempt.json").unlink()
    root = Path(service.repository.engine.url.database).parent
    backup_workspace(
        Path(service.repository.engine.url.database), root / "backup", root / "reports"
    )
    result = restore_workspace(root / "backup", root / "restored")
    assert result["restored_trial_bundle_stages"][identity] == stage
    assert not (root / "restored" / "quality-trials" / identity / "holdout-result.json").exists()
    suite_path = directory / "suite.json"
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    suite["label_origin"] = "forged"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    with pytest.raises(ProbeError, match="QUALITY_SUITE_CHANGED"):
        backup_workspace(
            Path(service.repository.engine.url.database), root / "bad-backup", root / "reports"
        )


@pytest.mark.parametrize("unsafe", [False, True])
def test_draft_still_rejects_bad_checksum_or_unsafe_schema(trial_data, unsafe):
    service, _, _, _, _ = trial_data
    root = Path(service.repository.engine.url.database).parent
    directory = service.artifact_root / uuid4().hex
    freeze(Path(service.repository.engine.url.database), directory)
    if unsafe:
        with sqlite3.connect(directory / "corpus.db") as db:
            db.execute("create view unsafe_object as select id from jobs")
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["database_sha256"] = file_sha(directory / "corpus.db")
        manifest.pop("corpus_sha256")
        manifest["corpus_sha256"] = digest(manifest)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        with (directory / "corpus.db").open("ab") as output:
            output.write(b"explicit synthetic checksum corruption")
    with pytest.raises(
        ProbeError, match="UNSAFE_BACKUP_DATABASE" if unsafe else "QUALITY_CORPUS_CHANGED"
    ):
        backup_workspace(
            Path(service.repository.engine.url.database), root / "rejected-backup", root / "reports"
        )
