"""New and legacy standard execution contracts, actual engine and persisted budgets."""

import asyncio
import re
from copy import deepcopy

import pytest
from starlette.testclient import TestClient
from test_feedback_requirement_negation import ExplanationModel
from test_review_feedback_repair import Model
from test_review_feedback_repair import workspace as workspace
from typer.testing import CliRunner

from work_observer.api.web import create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research import agent, requirements
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService, execute_project


def interrupt_legacy(repo, store, job, question):
    """Exercise the retained legacy engine with the historical unversioned input shape."""
    run = store.create(
        dict(
            question=question,
            job_ids=[job],
            offline=False,
            max_calls=5,
            timeout=180,
            allow_public=False,
            allow_proposals=False,
            approach="standard",
        )
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            agent._research(
                repo,
                question,
                Settings(),
                job_ids=[job],
                model=Model(cancel=True),
                checkpoint=(store, run["id"]),
                max_calls=5,
                allow_proposals=False,
                _qualification_guard=requirements.LEGACY_GUARD,
            )
        )
    store.save(run["id"], state="interrupted")
    return store.get(run["id"])


def test_legacy_standard_resume_keeps_input_history_old_guard_and_remaining_calls(workspace):
    repo, store, job, _, original, _, _ = workspace
    run = interrupt_legacy(repo, store, job, original["question"])
    before = deepcopy(store.load_checkpoint(run["id"]))
    assert before["result"]["model_calls"] == 3
    assert before["result"]["research_method_sha256"] == agent.method_fingerprint(
        requirement_guard=requirements.LEGACY_GUARD
    )
    assert (
        "qualification_validation" not in run["input"]
        and "qualification_validation" not in before["result"]
    )
    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=ExplanationModel("Docker经验优先，不能提升为必备。"),
            allow_proposals=False,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 5
    assert result["research_method_version"] == agent.LEGACY_RESEARCH_METHOD_VERSION
    assert result["research_method_sha256"] == before["result"]["research_method_sha256"]
    assert (
        "qualification_validation" not in result and store.get(run["id"])["input"] == run["input"]
    )
    after = store.load_checkpoint(run["id"])
    assert (
        after["max_calls"] == 5 and after["history"][: len(before["history"])] == before["history"]
    )


def test_new_resume_retains_fixed_guard_and_does_not_reset_budget(workspace):
    repo, store, job, _, original, _, _ = workspace
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                original["question"],
                Settings(),
                job_ids=[job],
                model=Model(cancel=True),
                max_calls=5,
                allow_proposals=False,
            )
        )
    run = next(row for row in store.list() if row["id"] != original["run_id"])
    validation = run["input"]["qualification_validation"]
    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=ExplanationModel("Docker经验优先，不能提升为必备。"),
            allow_proposals=False,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 4
    assert result["qualification_validation"] == validation == requirements.guard_contract()
    assert result["research_method_sha256"] == agent.method_fingerprint()
    assert store.load_checkpoint(run["id"])["max_calls"] == 5


def test_validation_change_mid_turn_stops_after_accounting_and_refuses_resume(
    workspace, monkeypatch
):
    repo, store, job, _, original, _, _ = workspace
    original_contract = requirements.guard_contract()

    def change():
        monkeypatch.setattr(
            requirements, "guard_contract", lambda: {**original_contract, "sha256": "0" * 64}
        )

    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            job_ids=[job],
            model=Model(after=change),
            max_calls=5,
            allow_proposals=False,
        )
    )
    assert result["status"] == "failed" and result["model_calls"] == 1
    assert result["stop_reason"] == "RESEARCH_VALIDATION_CHANGED_NEW_ROUND_REQUIRED"
    model = Model()
    with pytest.raises(ProbeError, match="VALIDATION_CHANGED"):
        asyncio.run(
            research(
                repo,
                original["question"],
                Settings(),
                checkpoint=(store, result["run_id"]),
                resume=True,
                model=model,
            )
        )
    assert not model.contexts and store.get(result["run_id"])["result"]["model_calls"] == 1


@pytest.mark.parametrize("key", ["qualification_validation", "_qualification_guard"])
def test_callers_cannot_opt_new_research_out_of_current_guard(workspace, key):
    repo, _, job, _, original, _, _ = workspace
    model = Model()
    with pytest.raises(ProbeError, match="VALIDATION_INTERNAL_ONLY"):
        asyncio.run(
            research(
                repo,
                original["question"],
                Settings(),
                job_ids=[job],
                model=model,
                **{key: requirements.LEGACY_GUARD},
            )
        )
    assert not model.contexts


def test_project_new_standard_round_uses_fixed_guard_and_keeps_reservation(workspace):
    repo, store, job, _, original, _, _ = workspace
    service = ProjectService(store)
    project = service.create("合成通用检查", "核对资格", [job], max_calls=5)
    project = service.add(
        project["id"], original["question"], revision=project["revision"], max_calls=5
    )
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ExplanationModel("Docker经验优先，不能提升为必备。"),
            max_steps=1,
        )
    )
    result = store.get(project["steps"][0]["run_id"])["result"]
    assert result["status"] == "completed" and result["model_calls"] == 3
    assert result["qualification_validation"] == requirements.guard_contract()
    assert service.usage(project)["reserved_calls"] == 5


def test_old_project_can_explicitly_refresh_for_new_method_without_resetting_usage(
    workspace, monkeypatch
):
    from work_observer.research.materials import material_state

    repo, store, job, _, original, _, _ = workspace
    service = ProjectService(store)
    project = service.create("合成旧项目", "核对资格", [job], max_calls=10)
    project = service.add(
        project["id"], original["question"], revision=project["revision"], max_calls=5
    )
    step = service.claim(project["id"])
    result = asyncio.run(
        agent._research(
            repo,
            original["question"],
            Settings(),
            job_ids=[job],
            project_id=project["id"],
            checkpoint=(store, step["run_id"]),
            model=Model(),
            max_calls=5,
            allow_proposals=False,
            _qualification_guard=requirements.LEGACY_GUARD,
        )
    )
    legacy_sha = agent.method_fingerprint(requirement_guard=requirements.LEGACY_GUARD)
    with monkeypatch.context() as patch:
        patch.setattr(agent, "method_fingerprint", lambda *args, **kwargs: legacy_sha)
        material = material_state(
            repo, original["question"], job_ids=[job], project_id=project["id"]
        )
    result.update(material_signature=material["signature"], material_basis=material["basis"])
    store.save(step["run_id"], state="finished", result=result)
    project = service.finish(project["id"], step["id"], state="waiting_review")
    old = deepcopy(store.get(step["run_id"]))
    project = service.refresh_waiting(
        project["id"],
        step["id"],
        repo,
        revision=project["revision"],
        note="明确按更新的检查口径重查",
        offline=False,
        max_calls=5,
    )
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ExplanationModel("Docker经验优先，不能提升为必备。"),
            max_steps=1,
        )
    )
    new = store.get(project["steps"][-1]["run_id"])["result"]
    assert new["status"] == "completed" and new["model_calls"] == 3
    assert new["qualification_validation"] == requirements.guard_contract()
    assert service.usage(project)["calls"] == 6 and service.usage(project)["reserved_calls"] == 10
    assert store.get(step["run_id"]) == old


def test_http_and_online_cli_standard_entrypoints_apply_versioned_guard(workspace, monkeypatch):
    repo, store, job, _, _, _, root = workspace
    settings = Settings(database_path=root / "app.db", raw_directory=root / "raw")
    text = "Docker经验优先，不能提升为必备。"
    with TestClient(
        create_app(settings, reports_dir=root / "reports", model=ExplanationModel(text)),
        base_url="http://127.0.0.1",
    ) as client:
        token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        headers = {"X-WO-Token": token}
        body = dict(question="合成HTTP标准资格", job_ids=[job], max_calls=5)
        blocked = client.post(
            "/api/research",
            headers=headers,
            json={**body, "qualification_validation": {"version": requirements.LEGACY_GUARD}},
        )
        assert blocked.status_code == 422
        response = client.post("/api/research", headers=headers, json=body)
        assert response.status_code == 202
        result = client.get("/api/research/" + response.json()["id"]).json()["result"]
        assert result["status"] == "completed" and result["model_calls"] == 3
        assert result["qualification_validation"] == requirements.guard_contract()

    class CLIModel(ExplanationModel):
        def __init__(self, *args, **kwargs):
            super().__init__(text)

    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *a, **k: settings))
    monkeypatch.setattr(agent, "ModelClient", CLIModel)
    result = CliRunner().invoke(
        app,
        [
            "research",
            "--question",
            "合成CLI标准资格",
            "--job-id",
            job,
            "--max-calls",
            "5",
            "--db",
            str(root / "app.db"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    run = store.list()[0]
    assert run["result"]["status"] == "completed" and run["result"]["model_calls"] == 3
    assert run["input"]["qualification_validation"] == requirements.guard_contract()
