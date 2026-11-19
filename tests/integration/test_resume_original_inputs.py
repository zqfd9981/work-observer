"""Resume from authoritative inputs with the same frozen evidence and remaining budget."""

import asyncio
from copy import deepcopy

import pytest
from test_selected_document_research import SelectedModel, documents
from test_source_first_research import source_workspace as source_workspace
from typer.testing import CliRunner

from work_observer.cli import app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research import agent
from work_observer.research.store import ResearchStore


def interrupted(workspace, tmp_path):
    repo, store, _ = workspace
    first, _ = documents(repo, tmp_path)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            agent.research(
                repo,
                "接口",
                Settings(),
                job_ids=[],
                public_document_ids=[first],
                max_calls=3,
                timeout=137,
                allow_public=True,
                allow_proposals=False,
                coverage_mode="question",
                model=SelectedModel(True),
            )
        )
    run = store.list()[0]
    assert run["result"]["model_calls"] == 2
    return run, deepcopy(store.load_checkpoint(run["id"]))


def test_resume_with_only_run_id_restores_doc_only_scope_and_original_options(
    source_workspace, tmp_path
):
    repo, store, _ = source_workspace
    run, checkpoint = interrupted(source_workspace, tmp_path)
    original_input = deepcopy(run["input"])
    result = asyncio.run(
        agent.research(
            repo,
            "接口",
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=SelectedModel(),
        )
    )
    assert result["status"] == "completed"
    assert result["scope"] == checkpoint["result"]["scope"]
    assert result["model_calls"] == 3
    assert store.get(run["id"])["input"] == original_input
    current = store.load_checkpoint(run["id"])
    assert current["max_calls"] == 3 and current["timeout"] == 137
    assert current["allow_public"] and not current["allow_proposals"]


def test_cli_resume_reopens_same_run_and_spends_only_the_remaining_call(
    source_workspace, tmp_path, monkeypatch
):
    _, store, _ = source_workspace
    run, _ = interrupted(source_workspace, tmp_path)
    original = deepcopy(run["input"])
    turns = []

    class ResumedModel(SelectedModel):
        def __init__(self, settings):
            super().__init__()

        async def turn(self, history):
            turns.append(history)
            return await super().turn(history)

    monkeypatch.setattr(agent, "ModelClient", ResumedModel)
    database = tmp_path / "app.db"
    monkeypatch.setattr(
        Settings, "load", classmethod(lambda *args: Settings(database_path=database))
    )
    result = CliRunner().invoke(app, ["research-resume", run["id"], "--db", str(database)])
    assert result.exit_code == 0, result.stdout
    reopened = ResearchStore(store.path, store.namespace)
    try:
        saved = reopened.get(run["id"])
        assert saved["state"] == "finished" and saved["result"]["status"] == "completed"
        assert saved["input"] == original
        assert saved["result"]["model_calls"] == 3 and len(turns) == 1
        assert len(reopened.list()) == 1
        assert reopened.load_checkpoint(run["id"])["timeout"] == 137
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "changed", [{"job_ids": None}, {"max_calls": 12}, {"timeout": 300}, {"allow_public": False}]
)
def test_resume_rejects_explicit_changes_before_another_model_attempt(
    source_workspace, tmp_path, changed
):
    repo, store, _ = source_workspace
    run, checkpoint = interrupted(source_workspace, tmp_path)

    class MustNotRun:
        async def turn(self, history):
            pytest.fail("显式改变原输入时不能再次调用模型")

    with pytest.raises(ProbeError, match="RESEARCH_INPUT_CHANGED_NEW_RUN_REQUIRED"):
        asyncio.run(
            agent.research(
                repo,
                "接口",
                Settings(),
                checkpoint=(store, run["id"]),
                resume=True,
                model=MustNotRun(),
                **changed,
            )
        )
    assert store.load_checkpoint(run["id"]) == checkpoint
    assert store.get(run["id"])["input"] == run["input"]
