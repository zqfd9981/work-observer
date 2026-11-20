"""Actual project repair/worker paths; all model turns are synthetic tool doubles."""

import asyncio
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from test_review_feedback_repair import Model, reject
from test_review_feedback_repair import workspace as workspace
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.maintenance import backup_workspace, restore_workspace
from work_observer.memory.lifecycle import forget_personal
from work_observer.memory.service import MemoryService
from work_observer.quality.feedback import VERSION
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import save_result
from work_observer.research.agent import research
from work_observer.research.project_feedback import repair_preview
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.research.worker import run_research_worker
from work_observer.storage.repository import Repository


@pytest.fixture
def project_case(workspace, request):
    repo, store, job, memory, direct, _, root = workspace
    service = ProjectService(store)
    project = service.create(
        "合成反馈项目",
        "核对Python和Docker资格",
        [job],
        max_calls=getattr(request, "param", 15),
        max_seconds=600,
        max_rounds=8,
    )
    project = service.add(
        project["id"], direct["question"], revision=project["revision"], max_calls=5, timeout=60
    )
    project = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=Model(original=True), max_steps=1
        )
    )
    source = project["steps"][0]
    review = reject(QualityReviewService(store, repo), source["run_id"])
    return repo, store, service, project, source, review, memory, root


def plan(case, **updates):
    repo, _, service, project, source, review, _, _ = case
    options = dict(
        revision=service.get(project["id"])["revision"],
        review_id=review["id"],
        note="明确重查优先限定",
        offline=False,
        max_calls=5,
        timeout=60,
    )
    options.update(updates)
    return service.repair_reviewed(project["id"], source["id"], repo, **options)


def test_repair_preserves_old_run_reserves_project_budget_and_unblocks_after_accept(project_case):
    repo, store, service, project, source, review, _, _ = project_case
    old = deepcopy(store.get(source["run_id"]))
    project = service.add(
        project["id"],
        "合成后续汇总",
        revision=project["revision"],
        depends_on=[source["id"]],
        offline=True,
    )
    with pytest.raises(ProbeError, match="QUALITY_REJECTION_REPAIR"):
        service.review(
            project["id"],
            source["id"],
            revision=project["revision"],
            action="accept",
            note="不能绕过拒绝",
            repository=repo,
        )
    assert service.claim(project["id"]) is None  # Rejected predecessor cannot release synthesis.
    project = plan(project_case)
    assert service.usage(project)["reserved_calls"] == 5
    assert store.get(source["run_id"]) == old
    replay = plan(project_case, revision=1)
    assert len(replay["steps"]) == 3
    model = Model()
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=model, max_steps=1)
    )
    repair = project["steps"][-1]
    result = store.get(repair["run_id"])["result"]
    from work_observer.research.historical_sources import VERSION as HISTORICAL_VERSION

    assert result["status"] == "completed"
    assert result["historical_sources_version"] == HISTORICAL_VERSION
    assert result["research_method_version"] == VERSION + "-" + HISTORICAL_VERSION
    assert result["review_feedback"]["review_id"] == review["id"]
    assert result["feedback_from"] == [source["run_id"]] and result["continued_from"] == []
    assert "旧结论错误标记" not in json.dumps(model.contexts, ensure_ascii=False)
    assert service.usage(project)["calls"] == 6 and service.usage(project)["reserved_calls"] == 10
    assert service.claim(project["id"]) is None  # Execution complete still awaits acceptance.
    project = service.review(
        project["id"],
        repair["id"],
        revision=project["revision"],
        action="accept",
        note="合成原文核对",
        repository=repo,
    )
    followup = service.claim(project["id"])
    assert followup["id"] == project["steps"][1]["id"]
    context = service.context(project["id"], followup, repo)
    assert [row["run_id"] for row in context["previous_findings"]] == [repair["run_id"]]
    assert store.get(source["run_id"]) == old


@pytest.mark.parametrize("project_case", [9], indirect=True)
def test_project_reservation_cannot_be_reopened_by_repair(project_case):
    _, store, service, project, source, _, _, _ = project_case
    with pytest.raises(ProbeError, match="PROJECT_REPAIR_BUDGET_EXHAUSTED"):
        plan(project_case)
    assert service.get(project["id"]) == project
    assert store.get(source["run_id"])["result"]["model_calls"] == 3
    project = plan(project_case, max_calls=4)
    assert service.usage(project)["reserved_calls"] == 5
    result = asyncio.run(
        execute_project(
            service,
            project["id"],
            project_case[0],
            Settings(),
            model=Model(),
            max_steps=1,
            worker_caps={"calls": 3, "seconds": 60, "public": 0},
        )
    )
    assert result["worker_batch"]["stop_reason"] == "worker_budget_exhausted"
    assert service.usage(result)["reserved_calls"] == 5
    result = asyncio.run(
        execute_project(
            service,
            project["id"],
            project_case[0],
            Settings(),
            model=Model(),
            max_steps=1,
            worker_caps={"calls": 4, "seconds": 60, "public": 0},
        )
    )
    assert service.usage(result)["reserved_calls"] == 9


def test_changed_review_fails_without_calls_then_explicit_replan_keeps_reservation(project_case):
    repo, store, service, project, source, _, _, _ = project_case
    project = plan(project_case)
    newer = reject(QualityReviewService(store, repo), source["run_id"], note="新版本核对理由")
    model = Model()
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=model, max_steps=1)
    )
    failed = project["steps"][-1]
    assert (
        failed["state"] == "failed"
        and failed["stop_reason"] == "RESEARCH_FEEDBACK_CHANGED_NEW_RUN_REQUIRED"
    )
    assert not model.contexts and service.usage(project)["reserved_calls"] == 10
    preview = repair_preview(service, project, failed, repo)
    assert preview["available"] and preview["review_id"] == newer["id"]
    project = service.repair_reviewed(
        project["id"],
        failed["id"],
        repo,
        revision=project["revision"],
        review_id=newer["id"],
        note="明确按新复核安排另一轮",
        offline=False,
        max_calls=5,
        timeout=60,
    )
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=Model(), max_steps=1)
    )
    assert store.get(project["steps"][-1]["run_id"])["result"]["status"] == "completed"
    assert service.usage(project)["reserved_calls"] == 15
    assert store.get(failed["run_id"])["state"] == "failed"


def test_pause_resume_keeps_project_reservation_and_review_pin(project_case):
    repo, store, service, project, _, review, _, _ = project_case
    project = plan(project_case)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            execute_project(
                service, project["id"], repo, Settings(), model=Model(cancel=True), max_steps=1
            )
        )
    interrupted = service.get(project["id"])["steps"][-1]
    assert interrupted["state"] == "interrupted"
    assert store.get(interrupted["run_id"])["result"]["model_calls"] == 3
    service.recover()
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=Model(), max_steps=1)
    )
    assert project["steps"][-1]["run_id"] == interrupted["run_id"]
    result = store.get(interrupted["run_id"])["result"]
    assert result["status"] == "completed" and result["model_calls"] == 4
    assert result["review_feedback"]["review_id"] == review["id"]
    assert service.usage(project)["reserved_calls"] == 10


def test_project_id_alone_cannot_create_a_repair_budget(project_case):
    repo, _, _, project, source, review, _, _ = project_case
    model = Model()
    with pytest.raises(ProbeError, match="PROJECT_CLAIM_REQUIRED"):
        asyncio.run(
            research(
                repo,
                source["question"],
                Settings(),
                project_id=project["id"],
                review_run_id=source["run_id"],
                review_id=review["id"],
                job_ids=source["job_ids"],
                max_calls=5,
                timeout=60,
                model=model,
            )
        )
    assert not model.contexts


def test_feedback_cannot_activate_memories_derived_from_rejected_source(project_case):
    repo, store, service, project, source, _, _, _ = project_case
    memory = MemoryService(repo)
    result = store.get(source["run_id"])["result"]
    candidate = memory.create(
        "knowledge",
        "合成资格核对：旧结论错误标记Docker必备",
        source_run_id=source["run_id"],
        evidence=result["evidence"],
        project_id=project["id"],
        scope="project",
        origin="agent",
    )
    with pytest.raises(ProbeError, match="MEMORY_DERIVED_DEPENDENCY_STALE"):
        memory.activate(candidate["id"])
    assert candidate["id"] not in {
        m["id"]
        for m in memory.recall(source["question"], source["job_ids"], project_id=project["id"])
    }
    project = plan(project_case)
    model = Model()
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=model, max_steps=1)
    )
    assert candidate["id"] not in {m["id"] for m in model.contexts[0]["memory_context"]}
    assert (
        next(row for row in memory.list() if row["id"] == candidate["id"])["status"] == "candidate"
    )


def test_http_saves_plan_only_and_cli_executes_offline_under_same_project(
    project_case, monkeypatch
):
    repo, store, service, project, source, review, _, root = project_case
    settings = Settings(database_path=root / "app.db", raw_directory=root / "raw")
    with TestClient(
        create_app(settings, reports_dir=root / "reports"), base_url="http://127.0.0.1"
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        detail = client.get("/api/projects/" + project["id"]).json()
        assert detail["steps"][0]["repair"]["review_id"] == review["id"]
        response = client.post(
            f"/api/projects/{project['id']}/steps/{source['id']}/repair",
            headers={"X-WO-Token": token},
            json=dict(
                revision=detail["revision"],
                review_id=review["id"],
                note="合成页面保存",
                offline=True,
                max_calls=4,
                timeout=60,
            ),
        )
        assert response.status_code == 201
        saved = response.json()["steps"][-1]
        assert saved["state"] == "queued" and saved["run_id"] is None
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *args, **kwargs: settings))
    response = CliRunner().invoke(
        app,
        [
            "product",
            "projects",
            "run",
            "--id",
            project["id"],
            "--db",
            str(root / "app.db"),
            "--reports-dir",
            str(root / "reports"),
        ],
    )
    assert response.exit_code == 0, response.stdout
    result = json.loads(response.stdout)
    run = store.get(result["steps"][-1]["run_id"])
    assert run["result"]["status"] == "evidence_only" and run["result"]["model_calls"] == 0
    assert run["result"]["review_feedback"]["review_id"] == review["id"]
    assert service.usage(service.get(project["id"]))["reserved_calls"] == 5


def test_new_review_can_replace_a_stale_unexecuted_plan_without_starting_it(project_case):
    repo, store, service, project, source, _, _, _ = project_case
    project = plan(project_case)
    pending = project["steps"][-1]
    newer = reject(
        QualityReviewService(store, repo), source["run_id"], note="保存计划后发现新的限定"
    )
    project = service.repair_reviewed(
        project["id"],
        pending["id"],
        repo,
        revision=project["revision"],
        review_id=newer["id"],
        note="明确重排",
        offline=False,
        max_calls=5,
        timeout=60,
    )
    assert pending["run_id"] is None and service.usage(project)["reserved_calls"] == 5
    assert project["steps"][-2]["state"] == "superseded"
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=Model(), max_steps=1)
    )
    assert store.get(project["steps"][-1]["run_id"])["result"]["status"] == "completed"
    assert service.usage(project)["reserved_calls"] == 10


def test_review_change_during_model_turn_stops_at_one_and_keeps_budget(project_case):
    repo, store, service, project, source, _, _, _ = project_case
    project = plan(project_case)

    def change():
        reject(QualityReviewService(store, repo), source["run_id"], note="本轮调用时收到后续复核")

    project = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=Model(after=change), max_steps=1
        )
    )
    result = store.get(project["steps"][-1]["run_id"])["result"]
    assert result["status"] == "failed" and result["model_calls"] == 1
    assert result["stop_reason"] == "RESEARCH_FEEDBACK_CHANGED_NEW_RUN_REQUIRED"
    assert service.usage(project)["reserved_calls"] == 10


def test_worker_reports_rejected_dependencies_as_waiting_without_calls(project_case):
    repo, _, service, project, source, _, _, _ = project_case
    project = service.review(
        project["id"],
        source["id"],
        revision=project["revision"],
        action="wait",
        note="合成等待核对",
        repository=repo,
    )
    # Preserve a formerly accepted scheduling state to model a later rejection.
    project["steps"][0]["state"] = "completed"
    with service.store.db:
        service._write(project)
    project = service.add(
        project["id"],
        "后续汇总",
        revision=project["revision"],
        depends_on=[source["id"]],
        offline=True,
    )
    result = asyncio.run(
        run_research_worker(
            service, repo, Settings(), project_id=project["id"], max_calls=0, max_public=0
        )
    )
    assert result["run_ids"] == [] and result["budget"]["actual"]["calls"] == 0
    assert result["waiting"][0]["blocked_dependencies"] == 1


def test_cli_can_plan_repair_then_backup_restore_and_forget_it(project_case, monkeypatch):
    repo, store, service, project, source, review, memory, root = project_case
    settings = Settings(database_path=root / "app.db", raw_directory=root / "raw")
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *args, **kwargs: settings))
    payload = root / "repair.json"
    payload.write_text(
        json.dumps(
            dict(
                step_id=source["id"],
                revision=project["revision"],
                review_id=review["id"],
                note="合成CLI复核私有标记",
                offline=False,
                max_calls=5,
                timeout=60,
            )
        ),
        encoding="utf-8",
    )
    response = CliRunner().invoke(
        app,
        [
            "product",
            "projects",
            "repair",
            "--id",
            project["id"],
            "--file",
            str(payload),
            "--db",
            str(root / "app.db"),
        ],
    )
    assert response.exit_code == 0, response.stdout
    project = json.loads(response.stdout)
    assert project["steps"][-1]["run_id"] is None
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=Model(), max_steps=1)
    )
    result = store.get(project["steps"][-1]["run_id"])["result"]
    saved = save_result(result, root / "reports")
    store.save(result["run_id"], saved={"report_id": saved["report_id"]})
    backup_workspace(root / "app.db", root / "backup", root / "reports")
    restored = restore_workspace(root / "backup", root / "restored")
    other_repo = Repository(Path(restored["database"]))
    other_store = ResearchStore(
        root / "restored/checkpoints.db", str(Path(restored["database"]).resolve())
    )
    other_repo.bind_research_store(other_store)
    other_service = ProjectService(other_store)
    assert other_service.get(project["id"]) == project
    assert (
        other_store.get(result["run_id"])["result"]["review_feedback"] == result["review_feedback"]
    )
    forget_personal(repo, store, memory["id"], root / "reports")
    assert service.get(project["id"])["state"] == "invalidated"
    assert not (root / "reports" / (saved["report_id"] + ".json")).exists()
    assert other_service.get(project["id"])["state"] == "active"
    forget_personal(other_repo, other_store, memory["id"], root / "restored/reports")
    assert other_service.get(project["id"])["state"] == "invalidated"
    assert other_store.get(result["run_id"])["state"] == "invalidated"
    other_store.close()
    other_repo.close()


def test_offline_preview_then_model_analysis_keeps_feedback_and_project_budget(project_case):
    repo, store, service, project, _, review, _, _ = project_case
    project = plan(project_case, offline=True)
    project = asyncio.run(execute_project(service, project["id"], repo, Settings(), max_steps=1))
    preview = project["steps"][-1]
    assert preview["state"] == "waiting_material" and service.usage(project)["reserved_calls"] == 5
    offered = repair_preview(service, project, preview, repo)
    assert offered["available"] and offered["offline_preview_done"]
    project = service.refresh_waiting(
        project["id"],
        preview["id"],
        repo,
        revision=project["revision"],
        note="明确从预览转为模型补查",
        offline=False,
        max_calls=5,
        timeout=60,
    )
    assert project["steps"][-1]["review_id"] == review["id"]
    project = asyncio.run(
        execute_project(service, project["id"], repo, Settings(), model=Model(), max_steps=1)
    )
    result = store.get(project["steps"][-1]["run_id"])["result"]
    assert (
        result["status"] == "completed" and result["review_feedback"]["review_id"] == review["id"]
    )
    assert service.usage(project)["reserved_calls"] == 10
