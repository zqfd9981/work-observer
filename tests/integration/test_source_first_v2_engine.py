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
