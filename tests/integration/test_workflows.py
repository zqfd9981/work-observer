"""日常串行流程验收：真实业务服务、隔离合成资料和明确模型替身，无收费调用。"""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.lifecycle import forget_project
from work_observer.reports.domain_updates import DomainUpdateService
from work_observer.reports.inbox import InboxService
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import JobAnalysis
from work_observer.storage.repository import Repository
from work_observer.workflow import service as workflow_module
from work_observer.workflow.service import WorkflowService, execute_workflow


class PipelineModel:
    def __init__(self):
        self.calls = 0

    async def turn(self, history):
        self.calls += 1
        if "你为已完成的岗位画像补充" in history[0]["content"]:
            name, args = (
                "finish_profile",
                {"domains": [], "interview_questions": ["请招聘方确认该合成岗位的交付边界。"]},
            )
        else:
            outputs = [
                json.loads(item["output"])
                for item in history
                if item.get("type") == "function_call_output"
            ]
            if not outputs:
                name, args = "query_jobs", {}
            else:
                evidence = [item for output in outputs for item in output.get("evidence", [])]
                read = {item.get("job_id") for item in evidence}
                pending = [
                    job for job in outputs[0]["jobs"] if job["has_detail"] and job["id"] not in read
                ]
                if pending:
                    name, args = "read_job", {"job_id": pending[0]["id"]}
                else:
                    name, args = (
                        "finish_research",
                        {
                            "claims": [
                                {
                                    "category": "task",
                                    "basis": "direct",
                                    "requirement": "unspecified",
                                    "text": item["title"] + "负责 Python 接口开发",
                                    "evidence_ids": [item["citation_key"]],
                                }
                                for item in evidence
                            ],
                            "gaps": ["合成服务链验收，不证明真实语义质量。"],
                        },
                    )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
            "call_id": name + str(self.calls),
        }
        return [call], call


@pytest.fixture
def workspace(tmp_path):
    database = tmp_path / "app.db"
    upgrade(database)
    repository = Repository(database)
    archive = RawArchive(tmp_path / "raw")

    def add(identity, text="负责 Python 接口开发并交付业务应用。"):
        return import_jd(
            repository,
            archive,
            ManualJD(
                title="合成岗位" + identity,
                company="合成公司" + identity,
                external_id=identity,
                description=text,
                data_kind="synthetic",
            ),
        )["job_id"]

    jobs = [add("a"), add("b")]
    store = ResearchStore(tmp_path / "checkpoints.db", str(database.resolve()))
    service = WorkflowService(store, repository)
    yield repository, store, service, jobs, add
    store.close()
    repository.close()


def test_saved_offline_workflow_makes_material_panel_without_pretending_review_complete(workspace):
    repository, _, service, jobs, _ = workspace
    model = PipelineModel()
    flow = service.create("材料核对", "比较 Python 任务与交付", jobs, terms=["Python"])
    assert flow["state"] == "saved" and flow["cycles"] == [] and model.calls == 0
    assert flow["estimate"]["worst_new_cycle"] == {"calls": 42, "seconds": 830}
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(JobAnalysis)) == 0
    first = asyncio.run(execute_workflow(service, flow["id"], Settings(), model=model))
    assert first["state"] == "waiting_material" and model.calls == 0
    assert [step["state"] for step in first["current_project"]["steps"]] == [
        "waiting_material",
        "waiting_material",
        "queued",
    ]
    capture = first["cycles"][0]["capture_id"]
    panel = DomainUpdateService(service.store, repository)._get("domain_update_captures", capture)
    assert (
        panel["sample"]["missing_profiles"] == 2 and panel["sample"]["current_profile_outputs"] == 0
    )
    again = asyncio.run(execute_workflow(service, flow["id"], Settings(), model=model))
    assert again["cycles"][0]["capture_id"] == capture and len(again["cycles"]) == 1
    assert again["usage"]["reserved"]["calls"] == 0
    assert len(DomainUpdateService(service.store, repository).list()["captures"]) == 1
    assert len(InboxService(repository).list()) == 2


def test_two_job_profile_project_review_restart_then_changed_material_report(workspace, tmp_path):
    repository, store, service, jobs, add = workspace
    flow = service.create(
        "完整合成链", "比较 Python 任务与交付，再主动核对反例", jobs, terms=["Python"]
    )
    model = PipelineModel()
    first = asyncio.run(
        execute_workflow(service, flow["id"], Settings(), model=model, allow_model=True)
    )
    assert first["state"] == "waiting_review"
    assert all(
        task["state"] == "completed" for task in first["cycles"][0]["profile_tasks"].values()
    )
    assert model.calls == 16
    assert first["usage"]["reserved"] == {"calls": 42, "seconds": 830}
    store.close()
    resumed_store = ResearchStore(
        tmp_path / "checkpoints.db", str(Path(repository.engine.url.database).resolve())
    )
    resumed = WorkflowService(resumed_store, repository)
    try:
        projects = ProjectService(resumed_store)
        project = projects.get(first["cycles"][0]["project_id"])
        for step in project["steps"][:2]:
            project = projects.review(
                project["id"],
                step["id"],
                revision=project["revision"],
                action="accept",
                note="合成测试逐项核对原文与反例",
                repository=repository,
            )
        second = asyncio.run(
            execute_workflow(resumed, flow["id"], Settings(), model=model, allow_model=True)
        )
        assert model.calls == 20 and second["state"] == "waiting_review"
        project = projects.get(project["id"])
        project = projects.review(
            project["id"],
            project["steps"][-1]["id"],
            revision=project["revision"],
            action="accept",
            note="合成汇总已核对",
            repository=repository,
        )
        complete = asyncio.run(
            execute_workflow(resumed, flow["id"], Settings(), model=model, allow_model=True)
        )
        assert complete["state"] == "completed" and model.calls == 20
        assert len(complete["cycles"]) == 1
        add("a", "负责 Java 业务接口和维护。")
        changed = asyncio.run(
            execute_workflow(resumed, flow["id"], Settings(), model=model, new_cycle=True)
        )
        assert (
            len(changed["cycles"]) == 2
            and changed["state"] == "waiting_material"
            and model.calls == 20
        )
        report = DomainUpdateService(resumed_store, repository).report(
            changed["cycles"][-1]["report_id"]
        )
        assert len(report["content_changes"]) == 1
        assert report["method_changes"]["profiles"]
        assert report["trend_status"] == "insufficient_comparable_time_series"
    finally:
        resumed_store.close()


def test_large_fresh_scope_stops_before_calls_and_refinement_keeps_budget(workspace):
    _, _, service, jobs, add = workspace
    jobs += [add(str(index)) for index in range(4)]
    model = PipelineModel()
    flow = service.create("范围预算", "比较接口任务", jobs)
    assert not flow["estimate"]["fits_remaining"]
    stopped = asyncio.run(
        execute_workflow(service, flow["id"], Settings(), model=model, allow_model=True)
    )
    assert (
        stopped["state"] == "needs_scope_refinement" and model.calls == 0 and not stopped["cycles"]
    )
    refined = service.refine(flow["id"], revision=stopped["revision"], job_ids=jobs[:2])
    assert refined["budget"] == flow["budget"] and refined["estimate"]["fits_remaining"]
    pending = asyncio.run(
        execute_workflow(
            service, flow["id"], Settings(), model=model, allow_model=True, max_calls=0
        )
    )
    assert pending["state"] == "ready" and model.calls == 0
    assert pending["cycles"][0]["project_id"] is None
    assert service.usage(pending)["reserved"]["calls"] == 24


def test_capture_commit_failure_retry_and_orphan_project_forgetting(
    workspace, tmp_path, monkeypatch
):
    repository, store, service, jobs, _ = workspace
    flow = service.create("不能复生的私有流程目标", "合成隐私目标", jobs)
    original = workflow_module._WorkflowUpdates._write
    tripped = []

    def fail_after_commit(instance, table, record):
        value = original(instance, table, record)
        if table == "domain_update_captures" and not tripped:
            tripped.append(True)
            raise ProbeError("SYNTHETIC_CAPTURE_ATTACH_FAILURE")
        return value

    with monkeypatch.context() as patch:
        patch.setattr(workflow_module._WorkflowUpdates, "_write", fail_after_commit)
        with pytest.raises(ProbeError, match="SYNTHETIC_CAPTURE_ATTACH_FAILURE"):
            asyncio.run(execute_workflow(service, flow["id"], Settings()))
    fixed = asyncio.run(execute_workflow(service, flow["id"], Settings()))
    assert len(DomainUpdateService(store, repository).list()["captures"]) == 1
    project_id, capture_id = fixed["cycles"][0]["project_id"], fixed["cycles"][0]["capture_id"]
    orphan = service._get(flow["id"])
    orphan["project_ids"], orphan["source_run_ids"] = [], []
    orphan["cycles"][0]["project_id"], orphan["cycles"][0]["run_ids"] = None, []
    service._save(orphan)
    forgotten = forget_project(repository, store, project_id, tmp_path / "reports")
    assert flow["id"] in forgotten["invalidated_workflow_ids"]
    erased = service._get(flow["id"])
    assert erased["state"] == "invalidated" and "私有流程目标" not in json.dumps(
        erased, ensure_ascii=False
    )
    assert erased["invalidation_dependencies"]["project_ids"] == [project_id]
    with pytest.raises(ProbeError, match="UPDATE_MEMORY_FORGOTTEN"):
        DomainUpdateService(store, repository)._get("domain_update_captures", capture_id)
    assert all(row["details"].get("cleared") for row in InboxService(repository).list())
    assert repository.job(jobs[0])["current"]["description_text"].startswith("负责 Python")


def test_workflow_http_and_actual_cli_default_to_offline(workspace, tmp_path, monkeypatch):
    repository, _, _, jobs, _ = workspace
    settings = Settings(
        database_path=Path(repository.engine.url.database), raw_directory=tmp_path / "raw"
    )
    with TestClient(
        create_app(settings, reports_dir=tmp_path / "reports"), base_url="http://127.0.0.1"
    ) as client:
        page = client.get("/").text
        headers = {"X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', page)[1]}
        created = client.post(
            "/api/workflows",
            headers=headers,
            json={"title": "HTTP默认无调用", "goal": "核对接口", "job_ids": jobs},
        )
        assert created.status_code == 201 and not created.json()["cycles"]
        identity = created.json()["id"]
        assert (
            client.post(f"/api/workflows/{identity}/run", headers=headers, json={}).status_code
            == 202
        )
        for _ in range(150):
            detail = client.get(f"/api/workflows/{identity}").json()
            if not detail["worker_running"]:
                break
            time.sleep(0.01)
        assert detail["state"] == "waiting_material"
        assert (
            client.get(f"/api/workflows/{identity}/artifacts/capture").json()["sample"][
                "scope_total"
            ]
            == 2
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, env_file=None: settings))
    payload = tmp_path / "workflow.json"
    payload.write_text(
        json.dumps({"title": "CLI默认无调用", "goal": "核对接口", "job_ids": jobs}),
        encoding="utf-8",
    )
    runner = CliRunner()
    created = runner.invoke(
        app, ["workflow", "create", "--file", str(payload), "--db", str(settings.database_path)]
    )
    assert created.exit_code == 0, created.output
    identity = json.loads(created.output)["id"]
    run = runner.invoke(
        app,
        [
            "workflow",
            "run",
            "--id",
            identity,
            "--db",
            str(settings.database_path),
            "--max-calls",
            "0",
        ],
    )
    assert run.exit_code == 0, run.output
    assert json.loads(run.output)["state"] == "waiting_material"


def test_offline_project_refresh_reserves_workflow_budget_and_cannot_repeat_across_cycles(
    workspace,
):
    repository, _, service, jobs, _ = workspace
    flow = service.create("离线升级预算", "核对接口", jobs, max_calls=24)
    first = asyncio.run(execute_workflow(service, flow["id"], Settings()))
    second = asyncio.run(execute_workflow(service, flow["id"], Settings(), new_cycle=True))
    assert service.usage(second)["reserved"]["calls"] == 0
    projects = ProjectService(service.store)
    first_project = projects.get(first["cycles"][0]["project_id"])
    assert first_project["budget"]["max_rounds"] == 12
    first_project = projects.refresh_waiting(
        first_project["id"],
        first_project["steps"][0]["id"],
        repository,
        revision=first_project["revision"],
        note="明确把已存材料从离线升级为模型补查",
        offline=False,
        max_calls=8,
        timeout=120,
    )
    claimed = projects.claim(first_project["id"])
    assert claimed["replaces_step_id"] == first_project["steps"][0]["id"]
    service.store.save(claimed["run_id"], state="failed")
    projects.finish(
        first_project["id"], claimed["id"], state="failed", reason="合成测试只验证预算不调用模型"
    )
    assert service.usage(service._get(flow["id"]))["reserved"]["calls"] == 24
    other = projects.get(second["cycles"][-1]["project_id"])
    other = projects.refresh_waiting(
        other["id"],
        other["steps"][0]["id"],
        repository,
        revision=other["revision"],
        note="另一离线周期请求模型",
        offline=False,
        max_calls=8,
        timeout=120,
    )
    with pytest.raises(ProbeError, match="WORKFLOW_LIFETIME_BUDGET_EXHAUSTED"):
        projects.claim(other["id"])
    assert projects.get(other["id"])["steps"][-1]["run_id"] is None


def test_unbound_workflow_source_key_cannot_claim_budget(workspace):
    _, store, _, jobs, _ = workspace
    projects = ProjectService(store)
    forged = projects.create(
        "手工来源键不能授权",
        "接口",
        jobs,
        max_calls=24,
        max_seconds=360,
        max_rounds=12,
        max_public=0,
        source_key="workflow:" + "a" * 32,
    )
    forged = projects.add(
        forged["id"], "接口", revision=forged["revision"], max_calls=8, timeout=120
    )
    with pytest.raises(ProbeError, match="WORKFLOW_PROJECT_UNBOUND"):
        projects.claim(forged["id"])
    assert projects.get(forged["id"])["steps"][0]["run_id"] is None


def test_workflow_invalidation_retries_notification_cleanup_after_tombstone(workspace, monkeypatch):
    repository, _, service, jobs, _ = workspace
    flow = service.create("必须清除的私文", "隐私流程目的", jobs)
    result = asyncio.run(execute_workflow(service, flow["id"], Settings()))
    project_id = result["cycles"][0]["project_id"]
    with monkeypatch.context() as patch:
        patch.setattr(
            InboxService,
            "invalidate_research",
            lambda *args: (_ for _ in ()).throw(ProbeError("SYNTHETIC_INBOX_FAILURE")),
        )
        with pytest.raises(ProbeError, match="SYNTHETIC_INBOX_FAILURE"):
            service.invalidate([], [], [project_id])
    tombstone = service._get(flow["id"])
    assert tombstone["state"] == "invalidated"
    assert "隐私流程目的" not in json.dumps(tombstone, ensure_ascii=False)
    repeated = service.invalidate([], [], [project_id])
    assert repeated["affected_workflow_ids"] == [flow["id"]]
    assert all(row["details"].get("cleared") for row in InboxService(repository).list())


def test_interrupted_profile_does_not_auto_repay_budget_and_explicit_retry_is_bounded(workspace):
    _, _, service, jobs, _ = workspace
    flow = service.create("中断画像", "核对Python", jobs[:1])

    class PausingModel:
        def __init__(self):
            self.waiting = asyncio.Event()

        async def turn(self, history):
            self.waiting.set()
            await asyncio.Event().wait()

    async def scenario():
        paused = PausingModel()
        task = asyncio.create_task(
            execute_workflow(service, flow["id"], Settings(), model=paused, allow_model=True)
        )
        await asyncio.wait_for(paused.waiting.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        stored = service.get(flow["id"])
        assert stored["state"] == "interrupted" and stored["usage"]["reserved"]["calls"] == 33
        service.recover()
        model = PipelineModel()
        no_retry = await execute_workflow(
            service, flow["id"], Settings(), model=model, allow_model=True
        )
        assert no_retry["state"] == "waiting_review" and model.calls == 0
        retried = await execute_workflow(
            service, flow["id"], Settings(), model=model, allow_model=True, retry_failed=True
        )
        assert len(retried["cycles"][0]["profile_attempts"]) == 2
        assert retried["usage"]["reserved"]["calls"] == 42
        assert retried["usage"]["unknown_actual_attempts"] == 1

    asyncio.run(scenario())


def test_rejected_profile_source_stops_workflow_reuse_and_fresh_retry_gets_distinct_cache(
    workspace,
):
    from work_observer.analysis.profiles import ProfileService
    from work_observer.quality.reviews import QualityReviewService
    from work_observer.quality.service import DIMENSIONS

    repository, store, service, jobs, _ = workspace
    model = PipelineModel()
    flow = service.create("画像拒绝资格", "核对接口", jobs)
    first = asyncio.run(
        execute_workflow(service, flow["id"], Settings(), model=model, allow_model=True)
    )
    profiles = ProfileService(repository)
    old = profiles.get(jobs[0])
    quality = QualityReviewService(store, repository)
    source = old["result"]["run_id"]
    packet = quality.packet(source)
    quality.submit(
        source,
        {
            "reviewer": "合成测试审核动作",
            "reviewer_kind": "human",
            "decision": "reject",
            "note": "机制测试，非实际独立人工语义标注",
            "result_sha256": packet["result_sha256"],
            "dimensions": {key: {"rating": "fail", "reason": "合成拒绝"} for key in DIMENSIONS},
            "claim_reviews": [
                {
                    "index": row["index"],
                    "support": "unsupported",
                    "requirement": "correct",
                    "note": "合成拒绝",
                }
                for row in packet["claims"]
            ],
        },
    )
    assert profiles.get(jobs[0])["stale"]
    count = model.calls
    stopped = asyncio.run(
        execute_workflow(service, flow["id"], Settings(), model=model, allow_model=True)
    )
    assert stopped["state"] == "waiting_review" and model.calls == count
    retried = asyncio.run(
        execute_workflow(
            service, flow["id"], Settings(), model=model, allow_model=True, retry_failed=True
        )
    )
    assert model.calls == count + 4
    assert retried["usage"]["reserved"]["calls"] == first["usage"]["reserved"]["calls"] + 9
    fresh = profiles.get(jobs[0])
    assert fresh["id"] != old["id"] and not fresh["stale"]
    cached = asyncio.run(profiles.analyze(jobs[0], Settings(), model=model))
    assert cached["cached"] and cached["id"] == fresh["id"] and model.calls == count + 4
