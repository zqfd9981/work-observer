"""Read old source windows within the frozen investigation scope and budget."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_domain_updates import updates as updates

from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research import historical_sources
from work_observer.research.agent import PROPOSAL_TOOLS, method_fingerprint, research
from work_observer.storage.models import JobObservation, JobSnapshot, SourceDocument


def test_old_body_windows_exclude_current_text_and_later_ingestion(updates):
    service, add = updates
    repo = service.repository
    text = "Python接口。" * 900 + "当时由平台团队发布。"
    job = add("one", text, city="上海")
    cutoff = now()
    add("one", "现在Java接口，岗位自行发布。", city="北京")
    late = add("late", "后来才入库。")
    with Session(repo.engine) as session, session.begin():
        for row in session.scalars(select(JobObservation).where(JobObservation.job_id == late)):
            row.observed_at = cutoff
    frozen = now()
    first = historical_sources.read(repo, job, cutoff, 0, [job], frozen)
    assert first["job"]["city"] == "上海"
    assert first["has_more"] and first["next_start"] == 5600
    last = historical_sources.read(repo, job, cutoff, first["next_start"], [job], frozen)
    assert not last["has_more"] and last["next_start"] is None
    assert "当时由平台团队发布" in last["evidence"][-1]["quote"]
    for evidence in first["evidence"] + last["evidence"]:
        assert evidence["quote"] == text[evidence["start"] : evidence["end"]]
        assert evidence["historical_cutoffs"] == [cutoff]
        assert evidence["processed_at"] <= cutoff and evidence["observed_at"] <= cutoff
    later = historical_sources.read(repo, job, frozen, 0, [job], frozen)
    assert "Java" in later["evidence"][0]["quote"]
    assert first["evidence"][0]["snapshot_id"] != later["evidence"][0]["snapshot_id"]
    unknown = historical_sources.read(repo, late, cutoff, 0, [late], frozen)
    assert unknown["status"] == "not_observed" and unknown["evidence"] == []


def test_absent_body_and_scope_time_window_integrity_boundaries(updates):
    service, add = updates
    repo = service.repository
    job = add("one")
    cutoff = now()
    with Session(repo.engine) as session, session.begin():
        for row in session.scalars(select(JobObservation).where(JobObservation.job_id == job)):
            row.kind = "list"
            snapshot = session.get(JobSnapshot, row.snapshot_id)
            snapshot.payload = {
                key: value for key, value in snapshot.payload.items() if key != "description"
            }
    missing = historical_sources.read(repo, job, cutoff, 0, [job], cutoff)
    assert missing["status"] == "body_unavailable" and missing["evidence"] == []
    for args, code in [
        (("outside", cutoff, 0, [job], cutoff), "RESEARCH_SCOPE_VIOLATION"),
        ((job, "2099-01-01T00:00:00+00:00", 0, [job], cutoff), "TIME_OUT_OF_SCOPE"),
        ((job, None, 0, [job], cutoff), "TIME_OUT_OF_SCOPE"),
        ((job, "2026-01-01T00:00:00", 0, [job], cutoff), "INVALID_RETRIEVAL_TIME"),
        ((job, cutoff, True, [job], cutoff), "INVALID_HISTORICAL_JOB_WINDOW"),
    ]:
        with pytest.raises(ProbeError, match=code):
            historical_sources.read(repo, *args)
    add("one", "新的正文。")
    frozen = now()
    with pytest.raises(ProbeError, match="INVALID_HISTORICAL_JOB_WINDOW"):
        historical_sources.read(repo, job, frozen, 9999, [job], frozen)
    with Session(repo.engine) as session:
        for document in session.scalars(select(SourceDocument)):
            Path(document.path).write_text("changed", encoding="utf-8")
    with pytest.raises(ProbeError, match="EVIDENCE_DOCUMENT_INTEGRITY_FAILED"):
        historical_sources.read(repo, job, frozen, 0, [job], frozen)


class HistoryModel:
    def __init__(self, job, cutoffs, interrupt=False, historical=True):
        self.job, self.cutoffs, self.interrupt = job, cutoffs, interrupt
        self.historical = historical

    async def turn(self, history):
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if self.interrupt and outputs:
            raise asyncio.CancelledError()
        if len(outputs) < len(self.cutoffs):
            name, args = (
                "read_historical_job",
                {"job_id": self.job, "as_of": self.cutoffs[len(outputs)], "start": 0},
            )
            if not self.historical:
                name, args = "read_job", {"job_id": self.job}
        else:
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "text": "两次合成来源正文："
                            + "；".join(row["evidence"][0]["quote"] for row in outputs),
                            "evidence_ids": [row["evidence"][0]["citation_key"] for row in outputs],
                        }
                    ],
                    "gaps": ["仅为合成机制核对，不是实际需求变化。"],
                },
            )
        call = dict(
            type="function_call", name=name, arguments=json.dumps(args), call_id=str(len(history))
        )
        return [call], call


@pytest.mark.parametrize("changed", [False, True])
def test_agent_resume_keeps_sources_evidence_links_and_spent_budget(updates, changed):
    service, add = updates
    repo, store = service.repository, service.store
    repo.bind_research_store(store)
    job = add("one", "负责Python接口开发。")
    before = now()
    if changed:
        add("one", "负责Java接口开发。")
    cutoffs = [before, now()]
    kwargs = dict(job_ids=[job], public_document_ids=[], coverage_mode="question", max_calls=4)
    run = store.create({"question": "合成来源对照", **kwargs})
    kwargs["checkpoint"] = (store, run["id"])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo, "合成来源对照", Settings(), model=HistoryModel(job, cutoffs, True), **kwargs
            )
        )
    saved = store.load_checkpoint(run["id"])
    frozen = saved["result"]["research_method_sha256"]
    add("one", "研究开始后才补入，不能替换已冻结来源。")
    result = asyncio.run(
        research(
            repo,
            "合成来源对照",
            Settings(),
            model=HistoryModel(job, cutoffs),
            resume=True,
            **kwargs,
        )
    )
    assert result["status"] == "completed", result
    assert result["model_calls"] == 4
    assert result["historical_sources_version"] == historical_sources.VERSION
    assert result["research_method_sha256"] == frozen
    assert len(result["claims"][0]["evidence_ids"]) == 2
    assert len(result["evidence"]) == (2 if changed else 1)
    assert {cutoff for row in result["evidence"] for cutoff in row["historical_cutoffs"]} == set(
        cutoffs
    )
    assert all("补入" not in row["quote"] for row in result["evidence"])
    assert all(
        row.get("local_only") for row in result["trace"] if row["tool"] == "read_historical_job"
    )
    assert result["public_reads"] == result["public_searches"] == 0


def test_optional_contract_preserves_legacy_method_and_global_proposals():
    original = deepcopy(PROPOSAL_TOOLS)
    expanded = historical_sources.proposals(PROPOSAL_TOOLS)
    assert (
        "read_historical_job" in expanded[0]["parameters"]["properties"]["supporting_tool"]["enum"]
    )
    assert PROPOSAL_TOOLS == original
    assert method_fingerprint() == method_fingerprint(historical_sources=False)
    assert method_fingerprint() != method_fingerprint(historical_sources=True)


def test_checkpoint_without_historical_reader_keeps_its_original_method(updates):
    service, add = updates
    repo, store = service.repository, service.store
    repo.bind_research_store(store)
    job = add("one")
    kwargs = dict(job_ids=[job], public_document_ids=[], coverage_mode="question", max_calls=3)
    run = store.create({"question": "原研究", **kwargs})
    kwargs["checkpoint"] = (store, run["id"])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo, "原研究", Settings(), model=HistoryModel(job, [now()], True, False), **kwargs
            )
        )
    saved = store.load_checkpoint(run["id"])
    result = saved["result"]
    result.pop("historical_sources_version")
    result["research_method_sha256"] = method_fingerprint(
        coverage_mode="question",
        requirement_guard=result.get("qualification_validation", {}).get("version"),
        answer_delivery_policy=result.get("answer_delivery_policy"),
        tool_budget_policy=result.get("tool_budget_policy"),
    )
    saved["history"][0]["content"] = saved["history"][0]["content"].replace(
        historical_sources.POLICY, ""
    )
    store.checkpoint(run["id"], saved)
    resumed = asyncio.run(
        research(
            repo,
            "原研究",
            Settings(),
            model=HistoryModel(job, [now()], historical=False),
            resume=True,
            **kwargs,
        )
    )
    assert resumed["status"] == "completed", resumed
    assert resumed["model_calls"] == 3
    assert "historical_sources_version" not in resumed
    assert resumed["research_method_sha256"] == result["research_method_sha256"]
