"""Automatic follow-ups share the same reservation rules as manual conversation steps."""

import asyncio
import json

from test_blueprint_continuity import MapWithFollowup
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.research.projects import ProjectService, execute_project


def prepare(workspace, *, budget=16):
    repo, store, jobs = workspace
    service = ProjectService(store)
    project = service.create(
        "合成补查预算", "接口工作", jobs, max_calls=budget, max_seconds=360, max_rounds=5
    )
    project = service.add(
        project["id"],
        "未执行的旧范围计划",
        revision=project["revision"],
        max_calls=10,
        timeout=180,
        approach="work_map",
    )
    original = dict(project["steps"][0])
    project = service.revise(
        project["id"], revision=project["revision"], goal="补充资料后核实接口责任", job_ids=jobs
    )
    project = service.add(
        project["id"],
        "合成当前地图",
        revision=project["revision"],
        max_calls=6,
        timeout=120,
        approach="work_map",
        coverage_mode="question",
    )
    return repo, service, project, original


def test_unclaimed_old_scope_plan_does_not_prevent_followup_under_original_budget(source_workspace):
    repo, service, project, original = prepare(source_workspace)
    result = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=MapWithFollowup(), max_steps=2
        )
    )
    old, first, followup = result["steps"]
    assert old["run_id"] is None and old["state"] == "waiting_review"
    assert old["max_calls"] == original["max_calls"] == 10 and old["timeout"] == 180
    assert old["scope_version"] == 1 and first["scope_version"] == followup["scope_version"] == 2
    assert first["state"] == followup["state"] == "waiting_review"
    assert first["origin"] == "user" and followup["origin"] == "agent"
    assert result["turns"][-1]["role"] == "assistant"
    assert followup["max_calls"] == 8 and followup["reply_to_step_id"] == first["id"]
    usage = service.usage(result)
    assert usage["reserved_calls"] == 14 <= result["budget"]["max_calls"] == 16
    assert usage["reserved_seconds"] == 240 <= result["budget"]["max_seconds"] == 360
    assert result["budget"] == project["budget"]
    followup_result = service.store.get(followup["run_id"])["result"]
    assert followup_result["continued_from"] == [first["run_id"]]
    context = service.context(result["id"], followup, repo)
    assert context["investigation_origin"] == "agent"
    assert context["reply_to"]["question_origin"] == "user"


def test_current_unclaimed_queue_keeps_its_allocation_and_blocks_overplanning(source_workspace):
    repo, service, project, _ = prepare(source_workspace)
    project = service.add(
        project["id"],
        "用户已安排的后续问题",
        revision=project["revision"],
        max_calls=8,
        timeout=120,
    )
    result = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=MapWithFollowup(), max_steps=1
        )
    )
    assert len(result["steps"]) == 3
    assert result["steps"][-1]["state"] == "queued" and result["steps"][-1]["run_id"] is None
    assert service.usage(result)["reserved_calls"] == 6
    assert result["steps"][1]["state"] == "waiting_review"


def test_whitespace_variant_of_existing_question_does_not_get_another_slot(source_workspace):
    repo, service, project, _ = prepare(source_workspace, budget=30)
    project = service.add(
        project["id"],
        "合成检查接口交付的责任边界",
        revision=project["revision"],
        max_calls=4,
        timeout=120,
    )

    class WhitespaceProposal(MapWithFollowup):
        async def turn(self, history):
            calls, raw = await super().turn(history)
            if calls[0]["name"] == "propose_investigation":
                args = json.loads(calls[0]["arguments"])
                args["question"] = "  " + args["question"] + "\n"
                calls[0]["arguments"] = json.dumps(args)
            return calls, raw

    result = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=WhitespaceProposal(), max_steps=1
        )
    )
    assert len(result["steps"]) == 3
    assert (
        len([step for step in result["steps"] if step["question"] == "合成检查接口交付的责任边界"])
        == 1
    )
    assert result["steps"][1]["state"] == "waiting_review"
