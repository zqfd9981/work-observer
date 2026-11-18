"""显式有界研究worker：合成模型和资料仅验证预算、领取与CLI机制。"""

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.research.projects import ProjectService
from work_observer.research.store import ResearchStore
from work_observer.research.worker import run_research_worker
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


class EvidenceModel:
    def __init__(self):
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
        elif not any(value.get("evidence") for value in outputs):
            name, arguments = "read_job", {"job_id": outputs[0]["jobs"][0]["id"]}
        else:
            evidence = next(value["evidence"] for value in outputs if value.get("evidence"))
            name, arguments = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "text": "合成岗位负责 Python 接口",
                            "evidence_ids": [evidence[0]["citation_key"]],
                        }
                    ],
                    "gaps": [],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(arguments),
            "call_id": name,
        }
        return [call], call


@pytest.fixture
def queue(tmp_path):
    database = tmp_path / "app.db"
    upgrade(database)
    repository = Repository(database)
    job = import_jd(
        repository,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成队列岗位",
            company="合成公司",
            description="负责 Python 接口开发。",
            data_kind="synthetic",
        ),
    )["job_id"]
    store = ResearchStore(tmp_path / "checkpoints.db", str(database.resolve()))
    yield repository, store, job
    store.close()
    repository.close()


def add_project(
    service, job, name, *, offline=False, depends_on=None, max_calls=6, allow_public=False
):
    project = service.create(name, "Python 职责", [job], max_calls=6, max_seconds=120, max_rounds=3)
    return service.add(
        project["id"],
        "Python 职责",
        revision=project["revision"],
        offline=offline,
        max_calls=max_calls,
        timeout=40,
        allow_public=allow_public,
        depends_on=depends_on,
    )


def test_worker_reserves_worst_round_and_preserves_project_budget_across_explicit_batches(queue):
    repository, store, job = queue
    service = ProjectService(store)
    projects = [add_project(service, job, name) for name in ("第一项目", "第二项目")]
    model = EvidenceModel()
    first = asyncio.run(
        run_research_worker(
            service, repository, Settings(), max_steps=3, max_calls=6, max_seconds=100, model=model
        )
    )
    assert len(first["processed"]) == 1
    assert first["budget"]["reserved"]["calls"] == 6
    assert first["budget"]["actual"]["calls"] == model.calls == 3
    assert first["stop_reason"] == "worker_budget_exhausted"
    finished_id = first["processed"][0]["project_id"]
    current = service.get(finished_id)
    current = service.add(
        current["id"],
        "显式新一轮仍需原项目预算",
        revision=current["revision"],
        max_calls=6,
        timeout=40,
    )
    repeated = asyncio.run(
        run_research_worker(
            service,
            repository,
            Settings(),
            project_id=finished_id,
            max_steps=3,
            max_calls=6,
            max_seconds=100,
            model=model,
        )
    )
    assert not repeated["processed"] and model.calls == 3
    assert repeated["skipped"][0]["reason"] == "project_budget_exhausted"
    assert service.usage(current)["reserved_calls"] == 6
    waiting_project = next(p for p in projects if p["id"] != finished_id)
    assert service.get(waiting_project["id"])["steps"][0]["run_id"] is None


def test_worker_recovers_one_scanned_run_keeps_waiting_dependencies_and_namespace(queue):
    repository, store, job = queue
    service = ProjectService(store)
    project = add_project(service, job, "待资料", offline=True)
    original = service.claim(project["id"])
    current = service.get(project["id"])
    current = service.add(
        current["id"],
        "等待前轮审核",
        revision=current["revision"],
        offline=True,
        depends_on=[original["id"]],
    )
    other_store = ResearchStore(store.path, "isolated-other-business")
    try:
        other = add_project(ProjectService(other_store), job, "其他库不能领取", offline=True)
        result = asyncio.run(
            run_research_worker(
                service,
                repository,
                Settings(),
                max_steps=6,
                max_calls=0,
                max_seconds=60,
                max_public=0,
            )
        )
        assert result["run_ids"] == result["recovered_run_ids"] == [original["run_id"]]
        assert result["processed"][0]["state"] == "waiting_material"
        assert result["waiting"][0]["blocked_dependencies"] == 1
        assert result["budget"]["reserved"]["calls"] == 0
        again = asyncio.run(
            run_research_worker(
                service,
                repository,
                Settings(),
                max_steps=6,
                max_calls=0,
                max_seconds=60,
                max_public=0,
            )
        )
        assert not again["processed"] and again["stop_reason"] == "no_ready_steps"
        assert ProjectService(other_store).get(other["id"])["steps"][0]["run_id"] is None
    finally:
        other_store.close()


def test_worker_claim_rechecks_caps_after_queue_changes_between_scan_and_execute(queue):
    repository, store, job = queue
    base = ProjectService(store)
    project = add_project(base, job, "换步竞态", offline=False)

    class ReplacedBeforeClaim(ProjectService):
        changed = False

        def claim(self, identity, **kwargs):
            if not self.changed:
                self.changed = True
                current = self.get(identity)
                current = self.revise(
                    identity, revision=current["revision"], goal="改变调查", job_ids=[job]
                )
                self.add(
                    identity,
                    "需要更高预算的新轮次",
                    revision=current["revision"],
                    max_calls=12,
                    timeout=40,
                )
            return super().claim(identity, **kwargs)

    model = EvidenceModel()
    result = asyncio.run(
        run_research_worker(
            ReplacedBeforeClaim(store),
            repository,
            Settings(),
            project_id=project["id"],
            max_calls=6,
            max_seconds=100,
            model=model,
        )
    )
    assert not result["processed"] and model.calls == 0
    assert result["stop_reason"] == "worker_budget_exhausted"
    assert all(step["run_id"] is None for step in base.get(project["id"])["steps"])


def test_worker_actual_cli_requires_once_and_releases_waiting_queue(queue, tmp_path, monkeypatch):
    repository, store, job = queue
    project = add_project(ProjectService(store), job, "CLI离线", offline=True, allow_public=True)
    monkeypatch.setattr(
        Settings,
        "load",
        classmethod(
            lambda cls, env_file=None: Settings(
                database_path=Path(repository.engine.url.database), raw_directory=tmp_path / "raw"
            )
        ),
    )
    runner = CliRunner()
    missing = runner.invoke(app, ["research-worker", "--db", str(repository.engine.url.database)])
    assert missing.exit_code != 0 and "WORKER_EXPLICIT_ONCE_REQUIRED" in missing.output
    arguments = [
        "research-worker",
        "--once",
        "--db",
        str(repository.engine.url.database),
        "--project-id",
        project["id"],
        "--max-calls",
        "0",
        "--max-public",
        "0",
        "--max-seconds",
        "60",
    ]
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["processed"][0]["state"] == "waiting_material"
    assert output["budget"]["actual"]["calls"] == 0
    repeated = runner.invoke(app, arguments)
    assert repeated.exit_code == 0
    assert not json.loads(repeated.output)["processed"]
