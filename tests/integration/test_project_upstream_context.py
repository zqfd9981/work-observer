import asyncio
from copy import deepcopy
from pathlib import Path

from starlette.testclient import TestClient
from test_dialogue_revisions import ConversationModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService, execute_project


def test_prior_downstream_research_carries_later_correction_into_next_conversation(
    source_workspace,
):
    repo, store, jobs = source_workspace
    projects = ProjectService(store)
    project = projects.create("合成连续修正", "接口责任", jobs[:1], max_calls=18, max_rounds=6)
    first = None
    for index in range(4):
        project = projects.add(
            project["id"],
            "接口责任" + str(index),
            revision=project["revision"],
            reply_to_step_id=first if index == 3 else None,
            max_calls=3,
            timeout=30,
            coverage_mode="question",
        )
        project = asyncio.run(
            execute_project(
                projects,
                project["id"],
                repo,
                Settings(),
                model=ConversationModel(record=index == 3),
                max_steps=1,
            )
        )
        assert store.get(project["steps"][-1]["run_id"])["result"]["status"] == "completed"
        first = project["steps"][0]["id"]
    downstream = project["steps"][1]
    stored = deepcopy(store.get(downstream["run_id"])["result"])
    correction = project["steps"][3]
    database = Path(repo.engine.url.database)
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=database.parent / "raw"),
            reports_dir=database.parent / "reports",
        ),
        base_url="http://127.0.0.1",
    ) as client:
        response = client.get("/api/projects/" + project["id"])
        assert response.status_code == 200, response.text
        affected = response.json()["steps"][1]["result"]["upstream_revision_notices"]
        assert affected["items"][0]["run_id"] == correction["run_id"]
    project = projects.add(
        project["id"],
        "接口责任继续核实",
        revision=project["revision"],
        reply_to_step_id=downstream["id"],
        max_calls=3,
        timeout=30,
        coverage_mode="question",
    )
    context = projects.context(project["id"], project["steps"][-1], repo)
    prior = next(
        row for row in context["previous_findings"] if row["run_id"] == downstream["run_id"]
    )
    assert prior["upstream_revision_notices"]["items"][0]["run_id"] == correction["run_id"]
    assert (
        prior["upstream_revision_notices"]["items"][0]["previous_run_id"]
        == project["steps"][0]["run_id"]
    )
    assert store.get(downstream["run_id"])["result"] == stored
    assert "upstream_revision_notices" not in stored
    # The correction's wording also becomes an ordinary ancestry dependency,
    # even when the bounded context selected only the older downstream answer.
    context["previous_findings"] = [prior]
    result = asyncio.run(
        research(
            repo,
            "接口责任继续核实",
            Settings(),
            job_ids=jobs[:1],
            conversation_context=context,
            project_id=project["id"],
            model=ConversationModel(record=False),
            max_calls=3,
            coverage_mode="question",
        )
    )
    assert result["status"] == "completed", result
    assert set(result["continued_from"]) == {downstream["run_id"], correction["run_id"]}
    saved = store.create({"question": "合成下游续问"})
    store.save(saved["id"], state="finished", result=result)
    assert saved["id"] in store.dependent_runs({correction["run_id"]})
