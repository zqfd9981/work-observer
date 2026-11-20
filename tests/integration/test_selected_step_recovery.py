import asyncio
import re
import time
from copy import deepcopy
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from test_dialogue_revisions import ConversationModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.api.web import create_app
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.projects import ProjectService, execute_project


class TemporaryFailure(ConversationModel):
    async def turn(self, history):
        if any(row.get("type") == "function_call_output" for row in history):
            raise ProbeError("MODEL_HTTP_ERROR")
        return await super().turn(history)


def test_selected_failed_step_resumes_the_same_run_before_older_queued_work(source_workspace):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    project = service.create("合成恢复调查", "接口责任", jobs[:1], max_calls=12)
    for question in ("较早排队的问题", "需要恢复的问题"):
        project = service.add(
            project["id"],
            question,
            revision=project["revision"],
            max_calls=4,
            timeout=60,
            coverage_mode="question",
        )
    selected = project["steps"][1]["id"]
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=TemporaryFailure(),
            max_steps=1,
            preferred_step_id=selected,
        )
    )
    assert project["steps"][0]["state"] == "queued"
    step = project["steps"][1]
    assert step["state"] == "failed"
    run_id = step["run_id"]
    before = deepcopy(project["budget"])
    project = service.review(
        project["id"],
        selected,
        revision=project["revision"],
        action="retry",
        note="明确继续原检查点",
    )
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ConversationModel(),
            max_steps=1,
            preferred_step_id=selected,
        )
    )
    assert project["steps"][0]["state"] == "queued"
    assert (
        project["steps"][1]["run_id"] == run_id and project["steps"][1]["state"] == "waiting_review"
    )
    assert service.usage(project)["reserved_calls"] == 4 and project["budget"] == before
    assert store.get(run_id)["result"]["model_calls"] <= 4
    with pytest.raises(ProbeError, match="STEP_NOT_READY"):
        service.claim(project["id"], preferred_step_id=selected)


def test_http_recovery_selects_the_requested_step_and_keeps_legacy_empty_run_body(source_workspace):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    project = service.create("合成HTTP恢复", "接口责任", jobs[:1], max_calls=12)
    for question in ("较早排队的问题", "需要恢复的问题"):
        project = service.add(
            project["id"],
            question,
            revision=project["revision"],
            max_calls=4,
            timeout=60,
            coverage_mode="question",
        )
    selected = project["steps"][1]["id"]
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=TemporaryFailure(),
            max_steps=1,
            preferred_step_id=selected,
        )
    )
    identity = project["steps"][1]["run_id"]
    model = ConversationModel()
    database = Path(repo.engine.url.database)
    with TestClient(
        create_app(
            Settings(database_path=database, raw_directory=database.parent / "raw"),
            reports_dir=database.parent / "reports",
            model=model,
        ),
        base_url="http://127.0.0.1",
    ) as client:
        headers = {
            "X-WO-Token": re.search(r'name="wo-token" content="([^"]+)"', client.get("/").text)[1]
        }
        path = "/api/projects/" + project["id"]
        current = client.get(path).json()
        assert current["steps"][1]["continuation"]["available"]
        assert current["steps"][1]["continuation"]["remaining_calls"] == 2
        response = client.post(
            path + "/steps/" + selected + "/review",
            headers=headers,
            json={"revision": current["revision"], "action": "retry", "note": "明确继续原检查点"},
        )
        assert response.status_code == 200, response.text
        denied = client.post(path + "/run", headers=headers, json={"step_id": "f" * 32})
        assert denied.status_code >= 400 and denied.json()["error_code"] == "STEP_NOT_READY"
        response = client.post(path + "/run", headers=headers, json={"step_id": selected})
        assert response.status_code == 202, response.text
        for _ in range(80):
            current = client.get(path).json()
            if not current["worker_running"]:
                break
            time.sleep(0.01)
        assert not current["worker_running"]
        assert current["steps"][1]["run_id"] == identity
        assert current["steps"][1]["state"] == "waiting_review"
        assert model.contexts[0]["question"] == "需要恢复的问题"
        assert current["usage"]["reserved_calls"] == 8
        contract = client.get("/api/openapi.json").json()
        assert not contract["paths"]["/api/projects/{id}/run"]["post"]["requestBody"]["required"]
        assert client.post(path + "/run", headers=headers).status_code == 202
