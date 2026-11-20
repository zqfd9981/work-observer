"""Ordinary conversation revisions reuse canonical claims, not map output or fake acceptance."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.reports.results import audit_result, render
from work_observer.research.agent import TOOLS, method_fingerprint, research
from work_observer.research.dialogue import POLICY, VERSION, DialogueAnswer, tools, validate
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive


class ConversationModel:
    def __init__(self, *, record=True, interrupt=False, revision_trigger="recheck"):
        self.record, self.interrupt, self.contexts = record, interrupt, []
        self.revision_trigger = revision_trigger

    async def turn(self, history):
        context = json.loads(history[1]["content"])
        self.contexts.append(context)
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        previous = (context.get("project_context") or {}).get("previous_findings", [])
        if not previous and (context.get("project_context") or {}).get("historical_reply"):
            previous = [context["project_context"]["historical_reply"]]
        if not outputs:
            if context["fixed_scope"]["jobs"]:
                name, args = "read_job", {"job_id": context["fixed_scope"]["jobs"][0]["id"]}
            else:
                name, args = "search_archived_sources", {"terms": ["接口"]}
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            receipt = outputs[0]["evidence"][0]
            evidence = receipt.get("citation_key", receipt["id"])
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
                        "trigger": self.revision_trigger,
                        "new_claim_indices": [0],
                        "evidence_ids": [evidence],
                        "reason": "同一原文重读，只支持任务和协作，不支持个人上线权推断。",
                        "aspects": [
                            {
                                "previous_excerpt": old["derived_claims"][0]["text"],
                                "decision": "revise",
                                "new_claim_indices": [0],
                                "evidence_ids": [evidence],
                                "reason": "任务及协作不证明个人拥有最终上线权。",
                            }
                        ],
                    }
                ]
            name = "finish_research"
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


def test_targeted_user_correction_is_recalled_before_revision_without_overwriting_old_answer(
    source_workspace,
    tmp_path,
):
    repo, store, jobs = source_workspace
    projects = ProjectService(store)
    project = projects.create("合成纠正流程", "接口责任边界", jobs[:1], max_calls=6)
    private = MemoryService(repo).create(
        "preference",
        "只讨论接口责任：SYNTHETIC_PRIVATE_CONTEXT",
        scope="project",
        project_id=project["id"],
        origin="user",
    )
    project = projects.add(
        project["id"],
        "接口工作",
        revision=project["revision"],
        coverage_mode="question",
        max_calls=3,
    )
    project = asyncio.run(
        execute_project(
            projects,
            project["id"],
            repo,
            Settings(),
            model=ConversationModel(),
            max_steps=1,
        )
    )
    step = project["steps"][0]
    original = deepcopy(store.get(step["run_id"])["result"])
    assert any(row["id"] == private["id"] for row in original["memory_used"])
    correction = MemoryService(repo).create(
        "correction",
        "针对本研究旧判断的纠正意见（用户提出，须按原文核实）\n"
        + "原判断："
        + original["claims"][0]["text"]
        + "\n我的纠正和理由：接口任务和与平台协作不证明个人独立上线权。",
        scope="project",
        project_id=project["id"],
        origin="user",
    )
    project = projects.add(
        project["id"],
        "核对我对个人独立上线的纠正意见",
        revision=project["revision"],
        reply_to_step_id=step["id"],
        coverage_mode="question",
        max_calls=3,
    )
    model = ConversationModel()
    project = asyncio.run(
        execute_project(
            projects,
            project["id"],
            repo,
            Settings(),
            model=model,
            max_steps=1,
        )
    )
    result = store.get(project["steps"][-1]["run_id"])["result"]
    assert result["status"] == "completed", result
    assert any(row["id"] == correction["id"] for row in result["memory_used"])
    assert any(row["id"] == correction["id"] for row in model.contexts[0]["memory_context"])
    revision = result["cognition_revisions"][0]
    assert revision["previous_run_id"] == step["run_id"]
    assert revision["previous_statement"] == original["claims"][0]["text"]
    assert revision["decision"] == "revise"
    assert revision["aspects"][0]["previous_excerpt"] == original["claims"][0]["text"]
    assert revision["aspects"][0]["evidence_ids"] == result["claims"][0]["evidence_ids"]
    assert revision["aspects"][0]["new_statements"] == [result["claims"][0]["text"]]
    assert store.get(step["run_id"])["result"] == original
    assert correction["status"] == "active" and correction["source_run_id"] is None
    assert not correction["evidence"]  # A user opinion is not original source evidence.
    from work_observer.memory.lifecycle import forget_personal

    forget_personal(repo, store, private["id"], tmp_path / "reports")
    validity = MemoryService(repo).validity(correction["id"])
    assert not validity["eligible"] and "forgotten" in validity["reasons"]
    erased = next(
        row
        for row in MemoryService(repo).list(include_history=True)
        if row["id"] == correction["id"]
    )
    assert erased["content"] == "[已忘记]" and erased["status"] == "forgotten"
    assert projects.get(project["id"])["state"] == "invalidated"
    assert repo.counts()["jobs"] == len(jobs)


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
        assert second["dialogue_revisions_version"] == VERSION
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
        assert decisions[-1]["aspects"] == revision["aspects"]
        assert any(row["run_id"] == second["run_id"] for row in context["previous_findings"])
        assert all(step["state"] == "waiting_review" for step in project["steps"])
        assert service.usage(project)["calls"] == 6
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "restriction", [None, "background_changed", "scope_removed", "unrelated_source"]
)
@pytest.mark.parametrize("source_kind", ["job", "material", "web"])
def test_explicit_reply_can_reconsider_a_retained_old_claim_after_source_update(
    source_workspace, tmp_path, restriction, source_kind, monkeypatch
):
    repo, store, other_jobs = source_workspace
    source = dict(
        title="合成版本岗位",
        company="合成公司",
        external_id="changed-source",
        data_kind="synthetic",
    )
    original_text = "岗位职责：负责接口开发；与平台团队协作。"
    updated_text = "岗位职责：负责接口开发；与平台团队协作，上线须经平台团队批准。"
    archive = PublicDocumentService(repo, tmp_path / "archive-raw")
    response_text = original_text

    async def fetch(url):
        return 200, {"content-type": "text/plain"}, response_text.encode()

    if source_kind == "job":
        job_id = import_jd(
            repo,
            RawArchive(tmp_path / "version-raw"),
            ManualJD(**source, description=original_text),
        )["job_id"]
        job_ids, selected = [job_id], None
    else:
        if source_kind == "material":
            document = archive.archive_text("接口交接说明", original_text)["document"]
        else:
            monkeypatch.setattr("work_observer.connectors.public_documents.pinned_request", fetch)
            document = asyncio.run(archive.read("https://example.com/interfaces"))["document"]
        job_ids, selected = [], [document["id"]]
    service = ProjectService(store)
    project = service.create(
        "正文更新后纠正",
        "接口任务与权限",
        job_ids,
        public_document_ids=selected,
        max_calls=6,
    )
    memories = MemoryService(repo)
    background = memories.create(
        "preference", "接口工作研究", scope="project", project_id=project["id"]
    )
    project = service.add(
        project["id"],
        "接口任务",
        revision=project["revision"],
        coverage_mode="question",
        max_calls=3,
    )
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ConversationModel(),
            max_steps=1,
        )
    )
    first_step = project["steps"][0]
    original = deepcopy(store.get(first_step["run_id"])["result"])
    if source_kind == "job":
        import_jd(
            repo,
            RawArchive(tmp_path / "updated-raw"),
            ManualJD(
                **source,
                description=updated_text,
            ),
        )
    else:
        if source_kind == "material":
            updated = archive.revise_text(document["id"], document["title"], updated_text)
        else:
            response_text = updated_text
            updated = asyncio.run(archive.read("https://example.com/interfaces"))
        project = service.revise(
            project["id"],
            revision=project["revision"],
            goal=project["goal"],
            job_ids=[],
            public_document_ids=[updated["document"]["id"]],
        )
    if restriction == "background_changed":
        memories.revise(background["id"], "新的用户目标")
    if restriction == "scope_removed":
        project = service.revise(
            project["id"],
            revision=project["revision"],
            goal=project["goal"],
            job_ids=[],
            public_document_ids=[],
        )
    if restriction == "unrelated_source":
        unrelated = archive.archive_text("另一份接口说明", updated_text)["document"]["id"]
        project = service.revise(
            project["id"],
            revision=project["revision"],
            goal=project["goal"],
            job_ids=other_jobs[:1] if source_kind == "job" else [],
            public_document_ids=[unrelated],
        )
    project = service.add(
        project["id"],
        "补充的审批要求改变了上轮独立上线的判断吗？",
        revision=project["revision"],
        reply_to_step_id=first_step["id"],
        coverage_mode="question",
        max_calls=3,
    )
    # A reopened service must recover the exact old statement as a historical target.
    service = ProjectService(store)
    context = service.context(project["id"], project["steps"][-1], repo)
    assert context["previous_findings"] == []
    assert context["reply_to"]["findings_included"] is False
    if restriction:
        assert "historical_reply" not in context
        assert store.get(first_step["run_id"])["result"] == original
        return
    historical = context["historical_reply"]
    assert historical["run_id"] == original["run_id"]
    assert historical["derived_claims"][0]["text"] == original["claims"][0]["text"]

    class UpdatedSourceModel(ConversationModel):
        async def turn(self, history):
            outputs, call = await super().turn(history)
            if call["name"] == "finish_research":
                answer = json.loads(call["arguments"])
                previous = json.loads(history[1]["content"])["project_context"]["historical_reply"]
                answer["claims"][0]["text"] = (
                    "新版原文写明上线须经平台团队批准，不能确认个人独立上线权限。"
                )
                answer["revisions"] = [
                    {
                        "previous_run_id": previous["run_id"],
                        "previous_claim_index": 0,
                        "decision": "revise",
                        "trigger": "new_evidence",
                        "new_claim_indices": [0],
                        "evidence_ids": answer["claims"][0]["evidence_ids"],
                        "reason": "新版增加平台团队批准条件，收窄旧的独立上线解释。",
                    }
                ]
                call["arguments"] = json.dumps(answer)
            return outputs, call

    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=UpdatedSourceModel(),
            max_steps=1,
        )
    )
    current_run = store.get(project["steps"][-1]["run_id"])
    result = current_run["result"]
    assert result is not None, current_run.get("error_code")
    assert result["status"] == "completed"
    assert result["continued_from"] == []  # The outdated answer is not current evidence.
    revision = result["cognition_revisions"][0]
    assert revision["previous_statement"] == original["claims"][0]["text"]
    assert revision["evidence_relation"] == "new_to_prior_run"
    assert not audit_result(result, repo)["stale_dependencies"]
    assert result["context_memory_used"][0]["id"] == background["id"]
    assert store.get(first_step["run_id"])["result"] == original
    project = service.add(
        project["id"],
        "再看原来的解释",
        revision=project["revision"],
        reply_to_step_id=first_step["id"],
        offline=True,
    )
    context = service.context(project["id"], project["steps"][-1], repo)
    decisions = context["historical_reply"]["derived_claims"][0]["followup_decisions"]
    assert decisions[-1]["run_id"] == result["run_id"]
    assert any(row["run_id"] == result["run_id"] for row in context["previous_findings"])
    memories.revise(background["id"], "更新后的背景")
    assert audit_result(result, repo)["stale_memory"]


@pytest.mark.parametrize("restriction", [None, "background_changed", "scope_removed"])
@pytest.mark.parametrize("reviewer_kind", ["agent_assisted", "human"])
@pytest.mark.parametrize("revision_trigger", ["recheck", "review"])
def test_rejected_explicit_reply_can_be_reconsidered_without_inheriting_its_rejection(
    source_workspace, restriction, reviewer_kind, revision_trigger
):
    repo, store, jobs = source_workspace
    service = ProjectService(store)
    project = service.create("合成拒绝后续问", "接口权限", jobs[:1], max_calls=6)
    memory = MemoryService(repo)
    background = memory.create(
        "preference", "合成接口研究目标", scope="project", project_id=project["id"]
    )
    project = service.add(
        project["id"],
        "接口任务与权限",
        revision=project["revision"],
        coverage_mode="question",
        max_calls=3,
    )
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ConversationModel(),
            max_steps=1,
        )
    )
    first_step = project["steps"][0]
    first = deepcopy(store.get(first_step["run_id"])["result"])
    quality = QualityReviewService(store, repo)
    review = quality.submit(
        first["run_id"],
        {
            "result_sha256": quality.packet(first["run_id"])["result_sha256"],
            "reviewer": "合成辅助核对",
            "reviewer_kind": reviewer_kind,
            "decision": "reject",
            "note": "合成拒绝：协作任务不能证明个人独立上线权限。",
            "dimensions": {key: {"rating": "fail", "reason": "合成机制检查"} for key in DIMENSIONS},
            "claim_reviews": [
                {
                    "index": 0,
                    "support": "unknown",
                    "requirement": "correct",
                    "note": "合成权限跨度错误",
                }
            ],
        },
    )
    if restriction == "background_changed":
        memory.revise(background["id"], "另一个合成目标")
    if restriction == "scope_removed":
        project = service.revise(
            project["id"],
            revision=project["revision"],
            goal=project["goal"],
            job_ids=jobs[1:],
        )
    project = service.add(
        project["id"],
        "重读原文核实上轮被拒绝的上线权限判断",
        revision=project["revision"],
        reply_to_step_id=first_step["id"],
        coverage_mode="question",
        max_calls=3,
    )
    context = service.context(project["id"], project["steps"][-1], repo)
    assert context["previous_findings"] == []
    if restriction:
        assert "historical_reply" not in context
        return
    historical = context["historical_reply"]
    assert historical["reason"] == "quality_rejected"
    assert historical["review_diagnostic"]["id"] == review["id"]
    assert historical["review_diagnostic"]["reviewer_kind"] == reviewer_kind
    assert historical["derived_claims"][0]["text"] == first["claims"][0]["text"]
    project = asyncio.run(
        execute_project(
            service,
            project["id"],
            repo,
            Settings(),
            model=ConversationModel(revision_trigger=revision_trigger),
            max_steps=1,
        )
    )
    second = store.get(project["steps"][-1]["run_id"])["result"]
    assert second["status"] == "completed"
    assert second["cognition_revisions"][0]["trigger"] == revision_trigger
    assert second["continued_from"] == []
    assert not audit_result(second, repo)["stale_dependencies"]
    assert second["cognition_revisions"][0]["previous_statement"] == first["claims"][0]["text"]
    assert second["cognition_revisions"][0]["previous_quality_review"]["id"] == review["id"]
    assert (
        "原质量核对未通过（人工核对）"
        if reviewer_kind == "human"
        else "原质量核对未通过（Agent辅助，非独立人审）"
    ) in render(second)
    assert store.get(first_step["run_id"])["result"] == first
    assert quality.list_run(first["run_id"])[0]["status"] == "rejected"
    assert service.usage(project)["reserved_calls"] == 6
    project = service.add(
        project["id"],
        "再核实这条被拒绝的旧解释",
        revision=project["revision"],
        reply_to_step_id=first_step["id"],
        offline=True,
    )
    context = service.context(project["id"], project["steps"][-1], repo)
    decisions = context["historical_reply"]["derived_claims"][0]["followup_decisions"]
    assert decisions[-1]["run_id"] == second["run_id"]
    assert any(row["run_id"] == second["run_id"] for row in context["previous_findings"])
    memory.revise(background["id"], "修订后的合成个人目标")
    assert audit_result(second, repo)["stale_memory"]
    context = service.context(project["id"], project["steps"][-1], repo)
    assert not context["previous_findings"] and "historical_reply" not in context


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


@pytest.mark.parametrize("missing", ["diagnostic", "id", "rejected_status", "same_run"])
def test_review_trigger_requires_the_selected_old_runs_actual_rejection(missing):
    answer, evidence, context = revision_case()
    answer.revisions[0].trigger = "review"
    historical = context["previous_findings"].pop()
    historical["review_diagnostic"] = {
        "id": "b" * 32,
        "status": "rejected",
        "reviewer_kind": "agent_assisted",
    }
    context["historical_reply"] = historical
    if missing == "diagnostic":
        historical.pop("review_diagnostic")
    if missing == "id":
        historical["review_diagnostic"].pop("id")
    if missing == "rejected_status":
        historical["review_diagnostic"]["status"] = "pending"
    if missing == "same_run":
        context["previous_findings"] = [deepcopy(historical)]
        historical["run_id"] = "c" * 32
    with pytest.raises(ValueError, match="明确复核反馈"):
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
    from work_observer.research import agent

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
    frozen["result"].pop("historical_sources_version")
    delivery_policy = frozen["result"].pop("answer_delivery_policy", "")
    budget_policy = frozen["result"].pop("tool_budget_policy", "")
    frozen["result"]["research_method_sha256"] = method_fingerprint(coverage_mode="question")
    frozen["result"]["research_method_version"] = frozen["result"][
        "research_method_version"
    ].replace("-" + VERSION, "")
    frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(POLICY, "")
    frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(delivery_policy, "")
    frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(budget_policy, "")
    frozen["history"][0]["content"] = agent.SYSTEM + agent.QUESTION_COVERAGE_POLICY
    payload = json.loads(frozen["history"][1]["content"])
    payload.pop("research_budget", None)
    frozen["history"][1]["content"] = json.dumps(payload, ensure_ascii=False)
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
