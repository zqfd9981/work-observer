"""独立审计项目CLI、领取互斥和半途建计划的恢复，全部为合成离线资料。"""

import asyncio
import json
import multiprocessing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from work_observer.api.projects import plan_project
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.data_quality.service import DataQualityService
from work_observer.knowledge.service import DomainKnowledgeService
from work_observer.maintenance import backup_workspace, restore_workspace
from work_observer.memory import lifecycle
from work_observer.memory.service import MemoryService
from work_observer.reports.results import save_result
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.locks import exclusive
from work_observer.storage.repository import Repository


@pytest.fixture
def project_setup(tmp_path):
    database = tmp_path / "app.db"
    upgrade(database)
    repository = Repository(database)
    job = import_jd(
        repository,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成CLI项目",
            company="合成公司",
            external_id="audit",
            description="负责 Python 业务接口。",
            data_kind="synthetic",
        ),
    )["job_id"]
    store = ResearchStore(tmp_path / "checkpoints.db", str(database.resolve()))
    service = ProjectService(store)
    project = service.create("独立审计", "核对 Python 职责", [job], source_key="audit-project")
    yield repository, store, service, project
    store.close()
    repository.close()


def test_project_cli_actual_offline_run_uses_existing_lock_without_nested_failure(
    project_setup, monkeypatch, tmp_path
):
    repository, _, service, project = project_setup
    project = service.add(project["id"], "Python 职责", revision=project["revision"], offline=True)
    monkeypatch.setattr(
        Settings,
        "load",
        classmethod(
            lambda cls, env_file=None: Settings(
                database_path=Path(repository.engine.url.database), raw_directory=tmp_path / "raw"
            )
        ),
    )
    result = CliRunner().invoke(
        app,
        [
            "product",
            "projects",
            "run",
            "--id",
            project["id"],
            "--db",
            str(repository.engine.url.database),
        ],
    )
    assert result.exit_code == 0, result.output
    record = json.loads(result.output)
    assert record["steps"][0]["state"] == "waiting_material"
    assert record["steps"][0]["stop_reason"] == "offline_no_model"
    assert service.usage(record)["calls"] == 0


def test_idempotent_plan_resume_after_two_steps_keeps_both_synthesis_dependencies(project_setup):
    _, _, service, project = project_setup
    for kind in ("investigate", "counterexample"):
        project = service.add(
            project["id"],
            "合成 " + kind,
            revision=project["revision"],
            kind=kind,
            offline=True,
            key=f"{project['id']}:initial:{kind}",
        )
    result = plan_project(service, project, offline=True)
    assert len(result["steps"]) == 3
    synthesis = next(step for step in result["steps"] if step["kind"] == "synthesis")
    assert set(synthesis["depends_on"]) == {
        step["id"] for step in result["steps"] if step["kind"] != "synthesis"
    }


def _other_process_project_run(database, checkpoint_path, identity, queue):
    repository = Repository(Path(database))
    store = ResearchStore(checkpoint_path, str(Path(database).resolve()))
    try:
        try:
            asyncio.run(execute_project(ProjectService(store), identity, repository, Settings()))
            queue.put("unexpectedly_executed")
        except ProbeError as exc:
            queue.put(exc.code)
    finally:
        store.close()
        repository.close()


def test_other_process_project_run_is_rejected_before_claim_or_state_change(project_setup):
    repository, store, service, project = project_setup
    project = service.add(project["id"], "Python 职责", revision=project["revision"], offline=True)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_other_process_project_run,
        args=(str(repository.engine.url.database), str(store.path), project["id"], queue),
    )
    with exclusive(repository.engine.url.database):
        process.start()
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join(5)
            pytest.fail("隔离子进程未在锁拒绝后退出")
        assert process.exitcode == 0
        assert queue.get(timeout=2) == "RESEARCH_BUSY"
    after = service.get(project["id"])
    assert after["steps"][0]["state"] == "queued"
    assert after["steps"][0]["run_id"] is None
    queue.close()
    queue.join_thread()


def test_pending_erasure_backup_checks_directory_and_restore_resumes_only_its_copies(
    project_setup, tmp_path, monkeypatch
):
    repository, store, _, _ = project_setup
    reports = tmp_path / "original-reports"
    preference = MemoryService(repository).create(
        "preference", "合成待忘记个人条件", subject="audit"
    )
    result = asyncio.run(research(repository, "合成离线报告", Settings(), offline=True))
    exported = save_result(result, reports)

    def stop_before_deletion(*args, **kwargs):
        raise ProbeError("SYNTHETIC_ERASURE_INTERRUPTION")

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle, "forget_reports", stop_before_deletion)
        with pytest.raises(ProbeError, match="SYNTHETIC_ERASURE_INTERRUPTION"):
            lifecycle.forget_personal(repository, store, preference["id"], reports)
    assert lifecycle.pending_erasures(store) == 1
    wrong_bundle = tmp_path / "wrong-bundle"
    with pytest.raises(ProbeError, match="PRIVACY_REPORT_DIRECTORY_MISMATCH"):
        backup_workspace(repository.engine.url.database, wrong_bundle, tmp_path / "wrong-reports")
    assert not wrong_bundle.exists()
    bundle = tmp_path / "pending-bundle"
    backup_workspace(repository.engine.url.database, bundle, reports)
    destination = tmp_path / "restored"
    restored = restore_workspace(bundle, destination)
    restored_repository = Repository(Path(restored["database"]))
    restored_store = ResearchStore(
        destination / "checkpoints.db", str(Path(restored["database"]).resolve())
    )
    try:
        assert lifecycle.pending_erasures(restored_store) == 1
        lifecycle.resume_erasures(restored_repository, restored_store, destination / "reports")
        assert lifecycle.pending_erasures(restored_store) == 0
        assert not (destination / "reports" / (exported["report_id"] + ".json")).exists()
        assert (reports / (exported["report_id"] + ".json")).is_file()
        assert lifecycle.pending_erasures(store) == 1
        assert restored_repository.counts()["jobs"] == repository.counts()["jobs"] == 1
    finally:
        restored_store.close()
        restored_repository.close()


def test_project_source_key_remains_idempotent_after_backup_restore_changes_namespace(
    project_setup, tmp_path
):
    repository, _, _, project = project_setup
    bundle, destination = tmp_path / "bundle", tmp_path / "restored"
    backup_workspace(repository.engine.url.database, bundle, tmp_path / "reports")
    restored = restore_workspace(bundle, destination)
    store = ResearchStore(destination / "checkpoints.db", str(Path(restored["database"]).resolve()))
    try:
        service = ProjectService(store)
        again = service.create(
            project["title"], project["goal"], project["job_ids"], source_key=project["source_key"]
        )
        assert again["id"] == project["id"]
        assert len(service.list()) == 1
    finally:
        store.close()


def test_reviewed_similar_job_link_does_not_silently_deduplicate_collection_denominators(
    project_setup, tmp_path
):
    repository, _, _, project = project_setup
    second = import_jd(
        repository,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成CLI项目",
            company="合成公司",
            external_id="another-entry",
            description="负责 Python 业务接口。",
            data_kind="synthetic",
        ),
    )["job_id"]
    first = project["job_ids"][0]
    DataQualityService(repository).review_duplicate(
        first, second, "linked", "合成核对为疑似同一岗位，保留两条来源记录"
    )
    collection = DomainKnowledgeService(repository).collection(limit=1)
    assert collection["counts"]["scope_total"] == 2
    assert len(collection["jobs"]) == 1 and collection["truncated"]
    statistics = RetrievalService(repository).stats(["Python"])
    assert statistics["sample"]["denominator"] == 2
    assert statistics["statistics"][0]["literal_jobs"] == 2
