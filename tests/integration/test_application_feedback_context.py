"""Attempt follow-ups carry eligible advice, never treat it as execution evidence."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_application_actions import ActionModel
from test_projects import setup as setup

from work_observer.config import Settings
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.research.applications import PREFIX
from work_observer.research.projects import ProjectService, execute_project


@pytest.mark.parametrize("oversize", [False, True])
def test_followup_retains_eligible_original_action_and_bounds_context(setup, tmp_path, oversize):
    repo, store, job = setup
    service = ProjectService(store)
    project = service.create("合成项目应用", "合成接口练习", [job], max_calls=12)
    memory = MemoryService(repo)
    note = memory.create(
        "preference",
        PREFIX + json.dumps({"background": "合成开发经历", "goal": "合成项目", "constraints": ""}),
        scope="project",
        project_id=project["id"],
    )
    project = service.add(project["id"], "合成应用建议", revision=project["revision"], max_calls=3)
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ActionModel(note["id"]),
            max_steps=1,
        )
    )
    original = project["steps"][0]
    result = store.get(original["run_id"])["result"]
    assert result["application_plan"] and original["state"] == "waiting_review"
    if oversize:
        result["application_plan"]["actions"][0]["assumptions"] = ["过长的合成前提" * 3000]
        store.save(original["run_id"], result=result)
    before = deepcopy(store.get(original["run_id"])["result"])
    document = PublicDocumentService(repo, tmp_path / "raw").archive_text(
        "合成尝试记录",
        "用户自述尝试了接口练习，观察到合成请求失败；未独立核实。",
        "合成用户回报",
    )["document"]
    project = service.revise(
        project["id"],
        revision=project["revision"],
        goal=project["goal"],
        job_ids=[job],
        public_document_ids=[document["id"]],
    )
    project = service.add(
        project["id"],
        "请核实原建议与尝试记录",
        revision=project["revision"],
        reply_to_step_id=original["id"],
        max_calls=3,
    )
    context = service.context(project["id"], project["steps"][-1], repo)
    previous = context["previous_findings"][0]
    assert previous["run_id"] == original["run_id"] and previous["review_state"] == "waiting_review"
    assert context["reply_to"]["application_plan_included"] is not oversize
    assert len(json.dumps(context, ensure_ascii=False)) <= 14000
    assert previous["derived_claims"]
    if oversize:
        assert "application_plan" not in previous and "未带入" in previous["application_plan_note"]
    else:
        assert previous["application_plan"] == before["application_plan"]
        assert "不是已执行事实" in previous["application_plan_note"]
    assert context["memory_dependencies"][0]["id"] == note["id"]
    assert document["id"] in project["steps"][-1]["public_document_ids"]
    assert store.get(original["run_id"])["result"] == before
    changed = json.loads(note["content"][len(PREFIX) :])
    changed["goal"] = "不同的合成目标"
    memory.revise(note["id"], PREFIX + json.dumps(changed))
    stale = service.context(project["id"], project["steps"][-1], repo)
    assert stale["previous_findings"] == []
    assert stale["reply_to"]["findings_included"] is False
