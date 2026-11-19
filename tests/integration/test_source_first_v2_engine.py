"""V2 provider-shaped calls, literal references and explicit unknowns; all synthetic."""

import asyncio
import json

import pytest
import test_source_first_research as source_fixture

from work_observer.config import Settings
from work_observer.research.agent import method_fingerprint, research
from work_observer.research.source_first import VERSION

SourceModel = source_fixture.SourceModel
source_workspace = source_fixture.source_workspace


def test_unit_feedback_guides_explicit_revision_in_the_original_budget(source_workspace, tmp_path):
    from jsonschema import Draft202012Validator

    from work_observer.connectors.manual import ManualJD, import_jd
    from work_observer.research.agent import ModelClient
    from work_observer.research.source_first import REQUIRED_FACETS
    from work_observer.storage.archive import RawArchive

    repo, store, _ = source_workspace
    job = import_jd(
        repo,
        RawArchive(tmp_path / "unit-raw"),
        ManualJD(
            title="合成长链路建设岗位",
            company="合成公司",
            description="岗位职责：\n负责"
            + "跨链路建设与调试" * 85
            + "，并在联调完成后提交交付文档。",
            data_kind="synthetic",
        ),
    )["job_id"]
    claim_text = "合成岗位负责跨链路建设与调试，并在联调完成后提交交付文档。"

    class RepairModel(ModelClient):
        def __init__(self):
            self.last_usage = {}

        async def turn(self, history):
            outputs = [
                json.loads(x["output"]) for x in history if x.get("type") == "function_call_output"
            ]
            view = next((x["source_view"] for x in reversed(outputs) if "source_view" in x), None)
            saved = next((x for x in reversed(outputs) if x.get("saved")), None)
            if not outputs:
                name, args = "query_jobs", {}
            elif not view:
                name, args = "read_job", dict(job_id=job)
            else:
                spans = view["jobs"][0]["sources"][0]["sentences"]
                refs = [x["sentence_id"] for x in spans if x["unit_id"] == spans[1]["unit_id"]]
                assert len(refs) == 2
                row = dict(
                    id="F1",
                    job_id=job,
                    facet="work_task",
                    state="stated",
                    actor="job_holder",
                    sentence_ids=refs[:1],
                    supersedes=[],
                    reason="合成来源单元登记，语义待核",
                )
                if not saved:
                    rows = [row] + [
                        dict(
                            id=f"F{i + 2}",
                            job_id=job,
                            facet=facet,
                            state="not_disclosed",
                            actor="job_holder",
                            sentence_ids=[],
                            supersedes=[],
                            reason="合成完整阅读，按维度记录未知",
                        )
                        for i, facet in enumerate(sorted(REQUIRED_FACETS - {"work_task"}))
                    ]
                    name, args = "record_source_findings", dict(findings=rows)
                elif outputs[-1].get("source_finding_check", {}).get("unit_repair_options"):
                    repair = outputs[-1]["source_finding_check"]["unit_repair_options"]["items"][0]
                    assert repair["action"] == "revise_finding_then_bind_full_unit"
                    assert repair["missing_from_finding"] == refs[1:]
                    row.update(
                        id="F7",
                        sentence_ids=repair["available_unit_sentence_ids"],
                        supersedes=["F1"],
                        reason="按反馈显式补齐完整单元并保留旧分项",
                    )
                    name, args = "record_source_findings", dict(findings=[row])
                else:
                    revised = any(x["id"] == "F7" for x in saved["active_findings"])
                    name, args = (
                        "finish_research",
                        dict(
                            claims=[
                                dict(
                                    category="task",
                                    basis="direct",
                                    requirement="unspecified",
                                    text=claim_text,
                                    bindings=[
                                        dict(
                                            finding_id="F7" if revised else "F1",
                                            sentence_ids=refs if revised else refs[:1],
                                        )
                                    ],
                                )
                            ],
                            gaps=["合成展示，非真实质量通过"],
                            unknown_finding_ids=[f"F{i}" for i in range(2, 7)],
                        ),
                    )
            current = next(x for x in self.tools if x["name"] == name)
            Draft202012Validator(current["parameters"]).validate(args)
            call = dict(
                type="function_call",
                name=name,
                arguments=json.dumps(args),
                call_id=str(len(history)),
            )
            return [call], call

    result = asyncio.run(
        research(
            repo,
            "合成完整单元修复",
            Settings(),
            job_ids=[job],
            approach="source_first",
            model=RepairModel(),
            max_calls=6,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 6
    assert result["claims"][0]["text"] == claim_text
    history = store.load_checkpoint(result["run_id"])["history"]
    proposals = [
        json.loads(row["arguments"]) for row in history if row.get("name") == "finish_research"
    ]
    assert all(row["claims"][0]["text"] == claim_text for row in proposals)
    assert next(x for x in result["source_findings"] if x["id"] == "F1")["active"] is False
    assert next(x for x in result["source_findings"] if x["id"] == "F7")["supersedes"] == ["F1"]
    assert (
        result["source_binding_check"]["binding_passed"]
        and not result["source_binding_check"]["semantic_approval"]
    )


@pytest.mark.parametrize("interrupt", [False, True])
def test_dynamic_tools_validate_real_call_shapes_and_resume_the_same_budget(
    source_workspace, interrupt
):
    import hashlib

    from jsonschema import Draft202012Validator

    from work_observer.research.agent import ModelClient

    repo, store, jobs = source_workspace
    contracts = []

    class DynamicModel(ModelClient):
        def __init__(self, stop=False):
            self.delegate = BoundModel()
            self.delegate.interrupt = stop
            self.last_usage = {}

        async def turn(self, history):
            current = {row["name"]: row for row in self.tools}
            contracts.append(
                dict(
                    sha256=hashlib.sha256(
                        json.dumps(self.tools, ensure_ascii=False, sort_keys=True).encode()
                    ).hexdigest(),
                    names=list(current),
                )
            )
            if not any(
                row.get("type") == "function_call_output"
                and "evidence" in json.loads(row["output"])
                for row in history
            ):
                assert "record_source_findings" not in current
            if not any(
                row.get("type") == "function_call_output" and json.loads(row["output"]).get("saved")
                for row in history
            ):
                assert "finish_research" not in current
            outputs, call = await self.delegate.turn(history)
            assert call["name"] in current
            Draft202012Validator(current[call["name"]]["parameters"]).validate(
                json.loads(call["arguments"])
            )
            return outputs, call

    options = dict(job_ids=jobs, approach="source_first", max_calls=6)
    if interrupt:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                research(repo, "合成动态引用", Settings(), model=DynamicModel(True), **options)
            )
        run = store.list()[0]
        assert run["result"]["model_calls"] == 5
        result = asyncio.run(
            research(
                repo,
                "合成动态引用",
                Settings(),
                checkpoint=(store, run["id"]),
                resume=True,
                model=DynamicModel(),
            )
        )
    else:
        result = asyncio.run(
            research(repo, "合成动态引用", Settings(), model=DynamicModel(), **options)
        )
    assert result["status"] == "completed"
    assert result["model_calls"] == (6 if interrupt else 5)
    assert len(result["tool_contracts"]) == result["model_calls"] == len(contracts)
    assert [row["call"] for row in result["tool_contracts"]] == list(
        range(1, result["model_calls"] + 1)
    )
    assert [row["sha256"] for row in result["tool_contracts"]] == [
        row["sha256"] for row in contracts
    ]
    assert (
        store.load_checkpoint(result["run_id"])["result"]["tool_contracts"]
        == result["tool_contracts"]
    )
    assert sum(row["tool"] == "record_source_findings" for row in result["trace"]) == 1
    if interrupt:
        assert contracts[-1] == contracts[-2]


def test_current_engine_exposes_exact_scope_enum_and_rejects_a_typo_without_guessing(
    source_workspace,
):
    from work_observer.research.agent import ModelClient

    repo, store, jobs = source_workspace
    typo = jobs[0][:-1]

    class ScopeModel(ModelClient):
        def __init__(self):
            self.delegate = BoundModel()
            self.last_usage = {}

        async def turn(self, history):
            definition = next(row for row in self.tools if row["name"] == "read_job")
            field = definition["parameters"]["properties"]["job_id"]
            assert field["enum"] == sorted(jobs)
            outputs, call = await self.delegate.turn(history)
            if call["name"] == "record_source_findings" and not any(
                row.get("type") == "function_call_output"
                and json.loads(row["output"]).get("invalid_finding_jobs")
                for row in history
            ):
                args = json.loads(call["arguments"])
                args["findings"][0]["job_id"] = typo
                call["arguments"] = json.dumps(args)
            return outputs, call

    result = asyncio.run(
        research(
            repo,
            "合成编号纠错",
            Settings(),
            job_ids=jobs,
            approach="source_first",
            model=ScopeModel(),
            max_calls=6,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 6
    checkpoint = store.load_checkpoint(result["run_id"])
    feedback = next(
        json.loads(row["output"])
        for row in checkpoint["history"]
        if row.get("type") == "function_call_output"
        and json.loads(row["output"]).get("invalid_finding_jobs")
    )
    assert feedback["saved"] is False
    assert feedback["error"] == "SOURCE_FIRST_FINDING_ID_OR_SCOPE"
    assert feedback["invalid_finding_jobs"] == [{"finding_id": "F1", "job_id": typo}]
    assert feedback["allowed_job_ids"] == sorted(jobs)
    assert all(row["job_id"] in jobs for row in result["source_findings"])
    assert any(typo in row.get("arguments", "") for row in checkpoint["history"])


class BoundModel(SourceModel):
    def __init__(self, defect=None):
        super().__init__()
        self.defect = defect

    async def turn(self, history):
        outputs, call = await super().turn(history)
        args = json.loads(call["arguments"])
        if call["name"] == "record_source_findings":
            for row in args["findings"]:
                row["actor"] = "job_holder"
        if call["name"] == "finish_research":
            registered = next(
                json.loads(row["arguments"])["findings"]
                for row in history
                if row.get("name") == "record_source_findings"
            )
            facts = [row for row in registered if row["state"] == "stated"]
            unknown = [row["id"] for row in registered if row["state"] != "stated"]
            claim = args["claims"][0]
            claim.pop("evidence_ids")
            claim.pop("finding_ids")
            claim["bindings"] = [
                {"finding_id": row["id"], "sentence_ids": row["sentence_ids"]} for row in facts
            ]
            args["unknown_finding_ids"] = unknown
            repaired = any(
                row.get("type") == "function_call_output"
                and json.loads(row["output"]).get("source_finding_check")
                for row in history
            )
            if not repaired and self.defect == "foreign_sentence":
                claim["bindings"][0]["sentence_ids"] = facts[1]["sentence_ids"]
            if not repaired and self.defect == "known_in_unknown_list":
                args["unknown_finding_ids"] = [facts[0]["id"], *unknown]
            if self.defect == "unknown_text_as_fact":
                claim["bindings"] = [
                    {"finding_id": unknown[0], "sentence_ids": facts[0]["sentence_ids"]}
                ]
                claim["text"] = "合成岗位没有任何开发职责，不需要接口开发。"
        call["arguments"] = json.dumps(args)
        return outputs, call


@pytest.mark.parametrize("defect", [None, "foreign_sentence", "known_in_unknown_list"])
def test_v2_derives_only_declared_literal_citations_and_keeps_original_words(
    source_workspace, defect
):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成v2职责研究",
            Settings(),
            job_ids=jobs,
            approach="source_first",
            model=BoundModel(defect),
            max_calls=6,
        )
    )
    assert result["status"] == "completed"
    assert result["model_calls"] == (5 if defect is None else 6)
    assert result["research_method_version"] == VERSION
    assert result["research_method_sha256"] == method_fingerprint("source_first")
    assert result["claims"][0]["text"] == (
        "两份合成岗位分别负责Python与Java接口开发，均保留团队协作。"
    )
    assert len(result["claims"][0]["evidence_ids"]) == 2
    assert result["claims"][0]["bindings"]
    assert result["claims"][0]["sentence_citations"]
    assert len(result["unknown_finding_ids"]) == 10
    assert all(row["actor"] == "job_holder" for row in result["source_findings"])
    saved = store.load_checkpoint(result["run_id"])
    receipts = [
        json.loads(row["output"])
        for row in saved["history"]
        if row.get("type") == "function_call_output"
    ]
    for receipt in receipts:
        if "source_view" not in receipt:
            continue
        assert receipt["source_view"]["format"] == "source-view-compact-v1"
        assert receipt["evidence"]  # Full provenance remains on the actual read response.
        for job in receipt["source_view"]["jobs"]:
            for source in job["sources"]:
                assert all("job_id" not in row for row in source["sentences"])
    actual = {row["id"]: row for row in result["evidence"]}
    for citation in result["claims"][0]["sentence_citations"]:
        assert citation["job_id"] == actual[citation["evidence_id"]]["job_id"]
        assert citation["snapshot_id"] == actual[citation["evidence_id"]]["snapshot_id"]
        assert "document_sha256" in citation
    if defect:
        feedback = next(
            row["source_finding_feedback"] for row in receipts if "source_finding_feedback" in row
        )
        assert "同维度+synthesis" not in feedback
        assert "多维关系不代表同口径可比" in feedback
    final = next(row for row in reversed(saved["history"]) if row.get("name") == "finish_research")
    proposal = json.loads(final["arguments"])
    assert "evidence_ids" not in proposal["claims"][0]
    assert "finding_ids" not in proposal["claims"][0]
    assert proposal["claims"][0]["text"] == result["claims"][0]["text"]
    assert not result["source_binding_check"]["semantic_approval"]


def test_v2_never_silently_deletes_or_rewrites_an_unknown_bound_exclusion(source_workspace):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成未知不能洗掉建设任务",
            Settings(),
            job_ids=jobs,
            approach="source_first",
            model=BoundModel("unknown_text_as_fact"),
            max_calls=5,
        )
    )
    assert result["status"] == "incomplete" and not result["claims"]
    assert result["model_calls"] == 5
    assert any(
        row["facet"] == "work_task" and row["state"] == "stated"
        for row in result["source_findings"]
    )
    saved = store.load_checkpoint(result["run_id"])
    proposals = [
        json.loads(row["arguments"])
        for row in saved["history"]
        if row.get("name") == "finish_research"
    ]
    assert proposals[0]["claims"][0]["text"] == "合成岗位没有任何开发职责，不需要接口开发。"
    feedback = [
        json.loads(row["output"])
        for row in saved["history"]
        if row.get("type") == "function_call_output"
    ][-1]
    assert feedback["source_finding_check"]["claim_finding_issues"]
    assert "unknown_cannot_support_exclusionary_claim" not in json.dumps(feedback)


def test_current_method_persists_multidimensional_notice_without_editing_the_proposal(
    source_workspace,
):
    repo, store, jobs = source_workspace

    class MultiAxis(BoundModel):
        async def turn(self, history):
            outputs, call = await super().turn(history)
            args = json.loads(call["arguments"])
            if call["name"] == "record_source_findings":
                views = next(
                    json.loads(row["output"])["source_view"]
                    for row in reversed(history)
                    if row.get("type") == "function_call_output"
                    and "source_view" in json.loads(row["output"])
                )
                job = views["jobs"][1]
                sentence = next(
                    row for row in job["sources"][0]["sentences"] if "协作" in row["text"]
                )
                args["findings"].append(
                    {
                        "id": "F90",
                        "job_id": job["job_id"],
                        "facet": "team_collaboration",
                        "actor": "job_holder",
                        "state": "stated",
                        "sentence_ids": [sentence["sentence_id"]],
                        "supersedes": [],
                        "reason": "原文明确团队协作；与接口任务是不同维度。",
                    }
                )
            if call["name"] == "finish_research":
                registered = next(
                    json.loads(row["arguments"])["findings"]
                    for row in history
                    if row.get("name") == "record_source_findings"
                )
                first = next(row for row in registered if row["facet"] == "work_task")
                second = next(row for row in registered if row["id"] == "F90")
                args["claims"][0]["bindings"] = [
                    {"finding_id": row["id"], "sentence_ids": row["sentence_ids"]}
                    for row in (first, second)
                ]
                args["claims"][0]["text"] = (
                    "两份已读片段分别说明接口开发与团队协作，不据此判断职责等同。"
                )
            call["arguments"] = json.dumps(args)
            return outputs, call

    result = asyncio.run(
        research(
            repo,
            "合成多维信息联系",
            Settings(),
            job_ids=jobs,
            approach="source_first",
            model=MultiAxis(),
            max_calls=5,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 5
    assert result["analysis_notes"] == result["source_binding_check"]["analysis_notes"]
    assert result["analysis_notes"][0]["index"] == 0
    assert {row["facet"] for row in result["analysis_notes"][0]["sides"]} == {
        "work_task",
        "team_collaboration",
    }
    assert not result["source_binding_check"]["semantic_approval"]
    proposed = next(
        row
        for row in reversed(store.load_checkpoint(result["run_id"])["history"])
        if row.get("name") == "finish_research"
    )
    assert json.loads(proposed["arguments"])["claims"][0]["text"] == result["claims"][0]["text"]
