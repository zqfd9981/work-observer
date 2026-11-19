"""Ordinary conversation revisions reuse canonical claims, not map output or fake acceptance."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import render
from work_observer.research.agent import TOOLS, method_fingerprint, research
from work_observer.research.dialogue import POLICY, DialogueAnswer, tools, validate
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore


class ConversationModel:
    def __init__(self, *, record=True, interrupt=False):
        self.record, self.interrupt, self.contexts = record, interrupt, []

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        previous = (context.get("project_context") or {}).get("previous_findings", [])
        if not outputs:
            if context["fixed_scope"]["jobs"]:
                name, args = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"]}
            else:
                name, args = "search_archived_sources", {"terms": ["接口"]}
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            evidence = outputs[0]["evidence"][0]["id"]
            args = {
                "claims": [
                    {
                        "category": "responsibility",
                        "basis": "inference",
                        "requirement": "unspecified",
                        "text": "待核实解释：接口任务可能由个人独立上线。"
                        if not previous
                        else "原文写接口开发及与平台团队协作，不能由此确认个人独立上线权限。",
                        "evidence_ids": [evidence],
                    }
                ],
                "gaps": ["独立上线权限仍需确认。"],
            }
            if previous and self.record:
                old = previous[0]
                args["revisions"] = [
                    {
                        "previous_run_id": old["run_id"],
                        "previous_claim_index": old["derived_claims"][0]["previous_claim_index"],
                        "decision": "revise",
                        "trigger": "recheck",
                        "new_claim_indices": [0],
                        "evidence_ids": [evidence],
                        "reason": "同一原文重读，只支持任务和协作，不支持个人上线权推断。",
                    }
                ]
            name = "finish_research"
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


@pytest.mark.parametrize("material_only", [False, True])
def test_three_turn_reopened_conversation_carries_pending_revision_without_a_map(
    source_workspace, tmp_path, material_only
):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    if material_only:
        PublicDocumentService(repo, tmp_path / "raw").archive_text(
            "合成项目说明",
            "接口开发任务，与平台团队协作。",
            "合成来源",
        )
    project = service.create(
        "合成普通追问",
        "接口任务与权限",
        [] if material_only else jobs[:1],
        max_calls=9,
        max_rounds=3,
    )
    project = service.add(
        project["id"],
        "接口工作",
        revision=project["revision"],
        coverage_mode="question",
        max_calls=3,
    )
    project = asyncio.run(
        execute_project(
            service, project["id"], repo, Settings(), model=ConversationModel(), max_steps=1
        )
    )
    first_step = project["steps"][0]
    first = deepcopy(store.get(first_step["run_id"])["result"])
    store.close()
    reopened = ResearchStore(store.path, store.namespace)
    try:
        service = ProjectService(reopened)
        project = service.add(
            project["id"],
            "为什么？",
            revision=project["revision"],
            reply_to_step_id=first_step["id"],
            coverage_mode="question",
            max_calls=3,
        )
        project = asyncio.run(
            execute_project(
                service, project["id"], repo, Settings(), model=ConversationModel(), max_steps=1
            )
        )
        second = reopened.get(project["steps"][1]["run_id"])["result"]
        revision = second["cognition_revisions"][0]
        assert second["status"] == "completed" and "work_map" not in second
        assert second["dialogue_revisions_version"] == "standard-dialogue-v1"
        assert revision["previous_statement"] == first["claims"][0]["text"]
        assert revision["previous_review_state"] == "waiting_review"
        assert revision["evidence_relation"] == "reread"
        assert "认识修正记录" in render(second)
        assert QualityReviewService(reopened, repo).packet(second["run_id"])[
            "cognition_revisions"
        ] == [revision]
        assert reopened.get(first_step["run_id"])["result"] == first
        project = service.add(
            project["id"],
            "再解释这点",
            revision=project["revision"],
            reply_to_step_id=first_step["id"],
            coverage_mode="question",
            max_calls=3,
        )
        model = ConversationModel(record=False)
        project = asyncio.run(
            execute_project(service, project["id"], repo, Settings(), model=model, max_steps=1)
        )
        context = model.contexts[0]["project_context"]
        old = next(row for row in context["previous_findings"] if row["run_id"] == first["run_id"])
        decisions = old["derived_claims"][0]["followup_decisions"]
        assert decisions[-1]["decision"] == "revise" and decisions[-1]["run_id"] == second["run_id"]
        assert any(row["run_id"] == second["run_id"] for row in context["previous_findings"])
        assert all(step["state"] == "waiting_review" for step in project["steps"])
        assert service.usage(project)["calls"] == 6
    finally:
        reopened.close()


def revision_case():
    source = {"id": "E1"}
    context = {
        "previous_findings": [
            {
                "run_id": "a" * 32,
                "review_state": "waiting_review",
                "derived_claims": [{"previous_claim_index": 5, "text": "原来的真实旧语句"}],
                "read_evidence_ids": ["E1"],
            }
        ]
    }
    answer = DialogueAnswer.model_validate(
        {
            "claims": [
                {
                    "category": "task",
                    "basis": "inference",
                    "requirement": "unspecified",
                    "text": "新的解释",
                    "evidence_ids": ["E1"],
                }
            ],
            "gaps": [],
            "revisions": [
                {
                    "previous_run_id": "a" * 32,
                    "previous_claim_index": 5,
                    "decision": "revise",
                    "trigger": "recheck",
                    "new_claim_indices": [0],
                    "evidence_ids": ["E1"],
                    "reason": "重读修正",
                }
            ],
        }
    )
    return answer, {"E1": source, "E2": {"id": "E2"}}, context


@pytest.mark.parametrize(
    "mistake",
    ["wrong_old_index", "new_claim_missing", "unread", "false_new", "unrelated", "fake_review"],
)
def test_invalid_revision_cannot_change_provenance(mistake):
    answer, evidence, context = revision_case()
    revision = answer.revisions[0]
    if mistake == "wrong_old_index":
        revision.previous_claim_index = 0
    if mistake == "new_claim_missing":
        revision.new_claim_indices = [1]
    if mistake == "unread":
        revision.evidence_ids = ["unknown"]
    if mistake == "false_new":
        revision.trigger = "new_evidence"
    if mistake == "unrelated":
        revision.evidence_ids = ["E2"]
    if mistake == "fake_review":
        revision.trigger = "review"
    with pytest.raises(ValueError):
        validate(answer, evidence, context)


@pytest.mark.parametrize("decision", ["retain", "revise", "withdraw", "unresolved"])
def test_each_revision_action_keeps_canonical_old_text_and_provisional_state(decision):
    answer, evidence, context = revision_case()
    answer.revisions[0].decision = decision
    if decision in {"withdraw", "unresolved"}:
        answer.revisions[0].new_claim_indices = []
    checked = validate(answer, evidence, context)[0]
    assert checked["decision"] == decision
    assert checked["previous_statement"] == "原来的真实旧语句"
    assert (
        checked["previous_claim_index"] == 5
        and checked["previous_review_state"] == "waiting_review"
    )
    assert checked["evidence_relation"] == "reread"


def test_finish_contract_is_copied_and_old_standard_fingerprint_is_preserved():
    before = deepcopy(TOOLS)
    finish = next(row for row in tools(TOOLS) if row["name"] == "finish_research")
    assert "revisions" in finish["parameters"]["properties"]
    assert "work_map" not in finish["parameters"]["properties"]
    assert TOOLS == before and "revisions" not in TOOLS[-1]["parameters"]["properties"]
    assert (
        method_fingerprint(requirement_guard="qualification-guard-v1")
        == "39a1ac282065db07b44b5c0bc259599ceb2f05a626d0fe478885c43e397dff24"
    )


def test_legacy_checkpoint_keeps_its_original_finish_contract(source_workspace):
    repo, store, jobs = source_workspace
    context = {
        "previous_findings": [
            {
                "run_id": "a" * 32,
                "review_state": "waiting_review",
                "derived_claims": [],
                "read_evidence_ids": [],
            }
        ]
    }
    run = store.create(
        {"question": "合成旧进度", "job_ids": jobs[:1], "coverage_mode": "question", "max_calls": 3}
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成旧进度",
                Settings(),
                job_ids=jobs[:1],
                coverage_mode="question",
                max_calls=3,
                checkpoint=(store, run["id"]),
                conversation_context=context,
                model=ConversationModel(interrupt=True),
            )
        )
    frozen = store.load_checkpoint(run["id"])
    frozen["result"].pop("dialogue_revisions_version")
    frozen["result"]["research_method_sha256"] = method_fingerprint(coverage_mode="question")
    frozen["result"]["research_method_version"] = frozen["result"][
        "research_method_version"
    ].replace("-standard-dialogue-v1", "")
    frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(POLICY, "")
    store.checkpoint(run["id"], frozen)
    store.save(run["id"], result=frozen["result"])
    result = asyncio.run(
        research(
            repo,
            "合成旧进度",
            Settings(),
            job_ids=jobs[:1],
            coverage_mode="question",
            max_calls=3,
            checkpoint=(store, run["id"]),
            conversation_context=context,
            resume=True,
            model=ConversationModel(record=False),
        )
    )
    assert result["status"] == "completed"
    assert "dialogue_revisions_version" not in result and "cognition_revisions" not in result
    assert result["model_calls"] == 3
