"""Expand a real isolated project scope, reread sources, and keep only dated old opinions."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_dialogue_revisions import ConversationModel
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.dependencies import DependencyAudit
from work_observer.reports.results import audit_result, render
from work_observer.research.projects import ProjectService, execute_project


class ExpandedModel(ConversationModel):
    async def turn(self, history):
        context = json.loads(history[1]["content"])
        scope = context["fixed_scope"]
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if len(outputs) == 1 and len(scope["jobs"]) > 1:
            read = {item.get("job_id") for item in outputs[0]["evidence"]}
            name, args = (
                "read_job",
                {"job_id": next(row["id"] for row in scope["jobs"] if row["id"] not in read)},
            )
        elif len(outputs) == 1 and scope.get("public_document_titles"):
            name, args = (
                "read_archived_document",
                {"document_id": scope["public_document_titles"][0]["id"], "start": 0},
            )
        else:
            if len(outputs) > 1:
                self.revision_trigger = "new_evidence"
            response, call = await super().turn(history)
            if call["name"] == "finish_research":
                args = json.loads(call["arguments"])
                refs = [row["evidence"][0]["id"] for row in outputs]
                args["claims"][0].update(basis="synthesis", evidence_ids=refs)
                args["revisions"][0]["evidence_ids"] = refs
                call["arguments"] = json.dumps(args)
            return response, call
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


@pytest.mark.parametrize("change", ["jobs", "documents", "goal"])
def test_expanded_scope_answer_is_usable_without_inheriting_outdated_scope_as_fact(
    source_workspace,
    tmp_path,
    change,
):
    repo, store, jobs = source_workspace
    projects = ProjectService(store)
    project = projects.create(
        "合成资料扩充",
        "接口任务边界",
        jobs[:1],
        public_document_ids=[],
        max_calls=14,
    )
    project = projects.add(
        project["id"],
        "接口任务",
        revision=project["revision"],
        coverage_mode="question",
        max_calls=3,
    )
    project = asyncio.run(
        execute_project(
            projects, project["id"], repo, Settings(), model=ConversationModel(), max_steps=1
        )
    )
    first = project["steps"][0]
    original = deepcopy(store.get(first["run_id"])["result"])
    selected = []
    if change == "documents":
        selected = [
            PublicDocumentService(repo, tmp_path / "materials").archive_text(
                "合成接口说明",
                "接口交接后由平台负责人核对发布，不能证明岗位个人有上线权。",
                "合成资料",
            )["document"]["id"]
        ]
    project = projects.revise(
        project["id"],
        revision=project["revision"],
        goal="接口任务的适用与协作边界" if change == "goal" else project["goal"],
        job_ids=jobs if change == "jobs" else jobs[:1],
        public_document_ids=selected,
    )
    project = projects.add(
        project["id"],
        "结合补充资料重读上轮接口责任判断",
        revision=project["revision"],
        reply_to_step_id=first["id"],
        coverage_mode="question",
        max_calls=4,
    )
    model = ExpandedModel()
    project = asyncio.run(
        execute_project(projects, project["id"], repo, Settings(), model=model, max_steps=1)
    )
    second = project["steps"][-1]
    result = store.get(second["run_id"])["result"]
    assert result["status"] == "completed", result
    audit = audit_result(result, repo)
    assert not audit["stale_dependencies"], audit
    assert DependencyAudit(repo).run(second["run_id"])["eligible"]
    context = model.contexts[0]["project_context"]
    assert context["previous_findings"] == []
    assert context["historical_reply"]["reason"] == "project_scope_changed"
    assert context["historical_reply"]["source_scope_version"] == 1
    assert not result["continued_from"]
    assert result["cognition_revisions"][0]["previous_statement"] == original["claims"][0]["text"]
    assert result["cognition_revisions"][0]["previous_scope_version"] == 1
    assert result["cognition_revisions"][0]["current_scope_version"] == 2
    assert "研究范围或目标已经调整" in render(result)
    if change == "jobs":
        assert {row["job_id"] for row in result["evidence"]} == set(jobs)
    if change == "documents":
        assert {
            row["public_document_id"] for row in result["evidence"] if row.get("public_document_id")
        } == set(selected)
    assert store.get(first["run_id"])["result"] == original
    assert not DependencyAudit(repo).run(first["run_id"])["eligible"]
    assert projects.usage(project)["reserved_calls"] == 7
    # A later scope revision must retain the earlier correction as dated advice,
    # rather than either losing it or making it factual ancestry of the next run.
    second_original = deepcopy(result)
    project = projects.revise(
        project["id"],
        revision=project["revision"],
        goal=project["goal"] + "，核对已有修正的边界",
        job_ids=project["job_ids"],
        public_document_ids=project["public_document_ids"],
    )
    project = projects.add(
        project["id"],
        "原判断已有后续修正，进一步核对其适用边界",
        revision=project["revision"],
        reply_to_step_id=first["id"],
        coverage_mode="question",
        max_calls=4,
    )
    third_model = ExpandedModel()
    project = asyncio.run(
        execute_project(
            projects,
            project["id"],
            repo,
            Settings(),
            model=third_model,
            max_steps=1,
        )
    )
    third = store.get(project["steps"][-1]["run_id"])["result"]
    assert third["status"] == "completed", third
    assert not audit_result(third, repo)["stale_dependencies"]
    historical = third_model.contexts[0]["project_context"]["historical_reply"]
    notices = historical["derived_claims"][0]["followup_decisions"]
    assert notices[0]["run_id"] == second["run_id"]
    assert notices[0]["source_scope_version"] == 2 and notices[0]["historical_scope"]
    assert not third["continued_from"]
    assert store.get(second["run_id"])["result"] == second_original
    assert projects.usage(project)["reserved_calls"] == 11
    third_step = project["steps"][-1]
    project = projects.add(
        project["id"],
        "对照原判断与当前范围内的后续修正",
        revision=project["revision"],
        reply_to_step_id=first["id"],
        coverage_mode="question",
        max_calls=3,
    )
    context = projects.context(project["id"], project["steps"][-1], repo)
    notices = context["historical_reply"]["derived_claims"][0]["followup_decisions"]
    assert [row["run_id"] for row in notices] == [second["run_id"], third_step["run_id"]]
    assert notices[0]["historical_scope"] and not notices[1]["historical_scope"]
