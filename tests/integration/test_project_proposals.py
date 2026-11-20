"""Follow-up planning preserves the answer and full investigation conditions."""

import asyncio
import json

from test_projects import EvidenceModel
from test_projects import setup as setup

from work_observer.config import Settings
from work_observer.reports.results import render
from work_observer.research.projects import ProjectService, execute_project

COMPLETION = ("逐项核对任务与责任边界；" * 60)[:600]
EVIDENCE_NEEDED = ("需查协作与最终决策的原文；" * 60)[:600]


class ProposalModel(EvidenceModel):
    async def turn(self, history):
        calls, raw = await super().turn(history)
        if calls[0]["name"] == "finish_research" and not any(
            row.get("name") == "propose_investigation" for row in history
        ):
            call = dict(
                type="function_call",
                name="propose_investigation",
                call_id="proposal:" + str(len(history)),
                arguments=json.dumps(
                    dict(
                        question="核实接口任务与最终决策的区别",
                        completion=COMPLETION,
                        evidence_needed=EVIDENCE_NEEDED,
                        kind="counterexample",
                    )
                ),
            )
            return [call], call
        return calls, raw


def create(service, job_id, *, max_calls=12):
    project = service.create("合成持续调查", "接口任务与责任", [job_id], max_calls=max_calls)
    return service.add(project["id"], "接口工作", revision=project["revision"], max_calls=4)


def test_proposal_keeps_complete_conditions_without_changing_the_research_budget(setup):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = create(service, job_id)
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ProposalModel(),
            max_steps=1,
        )
    )
    source, followup = project["steps"]
    result = store.get(source["run_id"])["result"]
    assert source["state"] == "waiting_review" and result["status"] == "completed"
    assert result["model_calls"] == 4
    assert followup["completion"] == COMPLETION
    assert followup["evidence_needed"] == EVIDENCE_NEEDED
    assert followup["reply_to_step_id"] == source["id"] and followup["origin"] == "agent"
    context = service.context(project["id"], followup, repo)
    assert context["completion"] == COMPLETION and context["evidence_needed"] == EVIDENCE_NEEDED
    report = render(result)
    assert COMPLETION in report and EVIDENCE_NEEDED in report


def test_concurrent_project_edit_during_planning_does_not_turn_completed_answer_into_failure(
    setup,
    monkeypatch,
):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = create(service, job_id)
    original_add = service.add
    changed = False

    def add(identity, question, **kwargs):
        nonlocal changed
        if kwargs.get("origin") == "agent" and not changed:
            changed = True
            current = service.get(identity)
            original_add(identity, "同时保存的用户追问", revision=current["revision"], offline=True)
        return original_add(identity, question, **kwargs)

    monkeypatch.setattr(service, "add", add)
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ProposalModel(),
            max_steps=2,
        )
    )
    source = project["steps"][0]
    assert source["state"] == "waiting_review"
    assert store.get(source["run_id"])["state"] == "finished"
    assert store.get(source["run_id"])["result"]["status"] == "completed"
    assert source["proposal_outcomes"][0]["reason"] == "PROJECT_CHANGED_REFRESH"
    assert project["steps"][-1]["question"] == "同时保存的用户追问"
    assert project["steps"][-1]["state"] == "waiting_material"
    assert service.usage(project)["calls"] == 4


def test_unarranged_proposal_keeps_its_reason_without_extra_execution(setup):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = create(service, job_id, max_calls=4)
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ProposalModel(),
            max_steps=3,
        )
    )
    assert len(project["steps"]) == 1
    source = project["steps"][0]
    assert source["proposal_outcomes"] == [
        dict(
            proposal_index=0,
            state="deferred",
            reason="call_budget",
        )
    ]
    result = store.get(source["run_id"])["result"]
    assert result["model_calls"] == 4 and result["status"] == "completed"
    assert result["investigation_proposals"][0]["evidence_needed"] == EVIDENCE_NEEDED


def test_scope_change_after_answer_does_not_apply_old_proposals_to_new_goal(setup, monkeypatch):
    repo, store, job_id = setup
    service = ProjectService(store)
    project = create(service, job_id)
    original_finish = service.finish

    def finish(identity, step_id, **kwargs):
        updated = original_finish(identity, step_id, **kwargs)
        service.revise(
            identity, revision=updated["revision"], goal="新的责任边界目标", job_ids=[job_id]
        )
        return updated

    monkeypatch.setattr(service, "finish", finish)
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ProposalModel(),
            max_steps=1,
        )
    )
    assert project["scope_version"] == 2 and len(project["steps"]) == 1
    assert project["steps"][0]["proposal_outcomes"][0]["reason"] == "scope_changed"
    assert store.get(project["steps"][0]["run_id"])["result"]["status"] == "completed"
