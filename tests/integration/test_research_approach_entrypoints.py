"""Approach propagation/immutable resume contracts; fake service is not model evidence."""

import re
import time

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from work_observer.api.web import ResearchInput, create_app
from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.store import ResearchStore
from work_observer.storage.database import upgrade


@pytest.fixture
def configured(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "app.db", raw_directory=tmp_path / "raw")
    upgrade(settings.database_path)
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, *a, **kw: settings))
    return settings


def auth(client):
    token = re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
    return {"X-WO-Token": token}


@pytest.mark.parametrize("requested", [None, "source_first"])
def test_http_start_persists_and_passes_selected_approach(configured, monkeypatch, requested):
    calls = []

    async def fake_research(repository, question, settings, **options):
        calls.append(options["approach"])
        store, identity = options["checkpoint"]
        assert store.get(identity)["input"]["approach"] == options["approach"]
        return {"status": "incomplete", "gaps": [], "question": question}

    monkeypatch.setattr("work_observer.api.web.research", fake_research)
    with TestClient(create_app(configured), base_url="http://127.0.0.1") as client:
        body = {"question": "Synthetic entrypoint question"}
        if requested:
            body["approach"] = requested
        response = client.post("/api/research", json=body, headers=auth(client))
        assert response.status_code == 202
        for _ in range(100):
            if calls:
                break
            time.sleep(0.01)
        assert calls == [requested or "standard"]
        rejected = client.post(
            "/api/research",
            json={"question": "Synthetic", "approach": "other"},
            headers=auth(client),
        )
        assert rejected.status_code == 422


@pytest.mark.parametrize("original", [None, "source_first"])
def test_http_resume_loads_original_or_legacy_standard(configured, monkeypatch, original):
    path = configured.database_path
    store = ResearchStore(path.parent / "checkpoints.db", str(path.resolve()))
    parameters = {"question": "Synthetic interrupted question"}
    if original:
        parameters["approach"] = original
    run = store.create(parameters)
    store.checkpoint(run["id"], {"version": 1})
    store.save(run["id"], state="interrupted")
    store.close()
    calls = []

    async def fake_research(repository, question, settings, **options):
        calls.append((options["approach"], options["resume"]))
        return {"status": "incomplete", "gaps": [], "question": question}

    monkeypatch.setattr("work_observer.api.web.research", fake_research)
    with TestClient(create_app(configured), base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/research/" + run["id"] + "/resume", json={}, headers=auth(client)
        )
        assert response.status_code == 202
        for _ in range(100):
            if calls:
                break
            time.sleep(0.01)
        assert calls == [(original or "standard", True)]


@pytest.mark.parametrize("requested", [None, "source_first"])
def test_cli_start_persists_and_passes_approach(configured, monkeypatch, requested):
    calls = []

    async def fake_research(repository, question, settings, **options):
        store, identity = options["checkpoint"]
        calls.append((options["approach"], store.get(identity)["input"]["approach"]))
        return {"status": "evidence_only", "stop_reason": "synthetic", "model_calls": 0}

    monkeypatch.setattr("work_observer.research.agent.research", fake_research)
    monkeypatch.setattr(
        "work_observer.reports.results.render", lambda result: "synthetic service double"
    )
    args = ["research", "--question", "Synthetic CLI question"]
    if requested:
        args.extend(["--approach", requested])
    response = CliRunner().invoke(app, args)
    assert response.exit_code == 0, (response.stdout, response.exception)
    assert calls == [(requested or "standard", requested or "standard")]
    rejected = CliRunner().invoke(app, [*args, "--approach", "other"])
    assert rejected.exit_code == 2
    assert len(calls) == 1


@pytest.mark.parametrize("original", [None, "source_first"])
def test_cli_resume_passes_original_or_legacy_standard(configured, monkeypatch, original):
    path = configured.database_path
    store = ResearchStore(path.parent / "checkpoints.db", str(path.resolve()))
    parameters = {"question": "Synthetic CLI interrupted question"}
    if original:
        parameters["approach"] = original
    run = store.create(parameters)
    store.checkpoint(run["id"], {"version": 1})
    store.save(run["id"], state="interrupted")
    store.close()
    calls = []

    async def fake_research(repository, question, settings, **options):
        calls.append((options["approach"], options["resume"]))
        return {"status": "incomplete"}

    monkeypatch.setattr("work_observer.research.agent.research", fake_research)
    monkeypatch.setattr(
        "work_observer.reports.results.render", lambda result: "synthetic service double"
    )
    response = CliRunner().invoke(app, ["research-resume", run["id"]])
    assert response.exit_code == 0, (response.stdout, response.exception)
    assert calls == [(original or "standard", True)]


@pytest.mark.parametrize("original", [None, "standard", "source_first"])
def test_store_resume_rejects_switch_and_does_not_rewrite_legacy_input(tmp_path, original):
    store = ResearchStore(tmp_path / "checkpoints.db", "synthetic")
    parameters = {"question": "Synthetic immutable input"}
    if original:
        parameters["approach"] = original
    run = store.create(parameters)
    store.checkpoint(run["id"], {"version": 1})
    active = original or "standard"
    store.prepare_execution(
        run["id"], {**parameters, "approach": active}, resume=True, supplied=["approach"]
    )
    # Unspecified caller defaults cannot switch a stored candidate.
    store.prepare_execution(run["id"], {**parameters, "approach": "standard"}, resume=True)
    changed = "source_first" if active == "standard" else "standard"
    with pytest.raises(ProbeError, match="RESEARCH_INPUT_CHANGED_NEW_RUN_REQUIRED"):
        store.prepare_execution(
            run["id"], {**parameters, "approach": changed}, resume=True, supplied=["approach"]
        )
    assert store.get(run["id"])["input"] == parameters
    store.close()


def test_new_unbound_store_can_seal_candidate_and_reject_invalid_value(tmp_path):
    store = ResearchStore(tmp_path / "checkpoints.db", "synthetic")
    run = store.create({"question": "Synthetic initial binding"})
    store.prepare_execution(
        run["id"], {"question": run["input"]["question"], "approach": "source_first"}
    )
    assert store.get(run["id"])["input"]["approach"] == "source_first"
    with pytest.raises(ProbeError, match="RESEARCH_APPROACH_INVALID"):
        store.prepare_execution(run["id"], {"approach": []}, resume=True, supplied=["approach"])
    store.close()


def test_standard_fingerprint_and_api_default_remain_legacy_v5():
    from work_observer.research.agent import RESEARCH_METHOD_VERSION, method_fingerprint

    assert ResearchInput(question="Synthetic default").approach == "standard"
    assert RESEARCH_METHOD_VERSION == "research-method-v5-responsibility-boundaries"
    assert (
        method_fingerprint() == "39a1ac282065db07b44b5c0bc259599ceb2f05a626d0fe478885c43e397dff24"
    )
