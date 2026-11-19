"""Dated research stays reusable as history, while current knowledge checks stay strict."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from test_domain_updates import updates as updates
from test_historical_job_research import HistoryModel

from work_observer.collection.contracts import now
from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.dependencies import DependencyAudit
from work_observer.memory.service import MemoryService
from work_observer.reports.results import audit_result, render
from work_observer.research import historical_sources
from work_observer.research.agent import research
from work_observer.research.projects import ProjectService, execute_project
from work_observer.research.store import ResearchStore
from work_observer.storage.models import SourceDocument


def comparison(service, add):
    repo, store = service.repository, service.store
    repo.bind_research_store(store)
    job = add("one", "负责Python接口开发。")
    before = now()
    add("one", "负责Java接口开发。")
    cutoffs = [before, now()]
    result = asyncio.run(
        research(
            repo,
            "合成历史接口对照",
            Settings(),
            job_ids=[job],
            public_document_ids=[],
            coverage_mode="question",
            max_calls=3,
            model=HistoryModel(job, cutoffs),
        )
    )
    assert result["status"] == "completed", result
    return job, cutoffs, result


def test_only_original_scope_trace_and_cutoff_version_qualify_as_history(updates):
    service, add = updates
    repo = service.repository
    job, cutoffs, original = comparison(service, add)
    old = original["evidence"][0]["id"]
    serialized = json.dumps(original, sort_keys=True)
    assert old in historical_sources.historical_evidence_ids(repo, original)
    cases = []
    missing_contract = deepcopy(original)
    missing_contract.pop("historical_sources_version")
    cases.append(missing_contract)
    no_trace = deepcopy(original)
    no_trace["trace"] = []
    cases.append(no_trace)
    outside_scope = deepcopy(original)
    outside_scope["scope"]["jobs"] = []
    cases.append(outside_scope)
    wrong_version = deepcopy(original)
    wrong_version["evidence"][0]["historical_cutoffs"] = [cutoffs[1]]
    cases.append(wrong_version)
    wrong_window = deepcopy(original)
    wrong_window["trace"][0]["end"] = 1
    cases.append(wrong_window)
    for result in cases:
        assert old not in historical_sources.historical_evidence_ids(repo, result)
        audit = audit_result(result, repo)
        assert any(row["evidence_id"] == old for row in audit["changed_sources"])
        assert audit["stale_dependencies"]
    assert json.dumps(original, sort_keys=True) == serialized
    assert not audit_result(original, repo)["stale_dependencies"]


def test_damaged_archives_block_history_and_old_evidence_cannot_be_current_knowledge(updates):
    service, add = updates
    repo = service.repository
    job, cutoffs, result = comparison(service, add)
    old = result["evidence"][0]
    memory = MemoryService(repo)
    candidate = memory.create(
        "knowledge",
        result["claims"][0]["text"],
        evidence=[old],
        source_run_id=result["run_id"],
        job_id=job,
        origin="agent",
    )
    with pytest.raises(ProbeError, match="MEMORY_DERIVED_DEPENDENCY_STALE"):
        memory.activate(candidate["id"])
    assert not memory.validity(candidate["id"])["eligible"]
    with Session(repo.engine) as session:
        document = session.get(SourceDocument, old["document_id"])
        Path(document.path).write_text("changed", encoding="utf-8")
    audit = audit_result(result, repo)
    assert any(not row["retained_evidence_valid"] for row in audit["changed_sources"])
    assert audit["stale_dependencies"]
    assert not DependencyAudit(repo).run(result["run_id"])["eligible"]


def test_reopened_project_carries_dated_understanding_and_cutoffs_into_next_question(updates):
    service, add = updates
    repo, store = service.repository, service.store
    repo.bind_research_store(store)
    job = add("one", "负责Python接口开发。")
    cutoff = now()
    add("one", "负责Java接口开发。")
    projects = ProjectService(store)
    project = projects.create("合成历史接口研究", "核对历史工作理解", [job], max_calls=8)
    project = projects.add(
        project["id"],
        "合成历史接口",
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
            model=HistoryModel(job, [cutoff]),
            max_steps=1,
        )
    )
    previous = project["steps"][0]
    original = deepcopy(store.get(previous["run_id"])["result"])
    reopened = ResearchStore(store.path, store.namespace)
    try:
        projects = ProjectService(reopened)
        project = projects.add(
            project["id"],
            "为什么这样理解？",
            revision=project["revision"],
            reply_to_step_id=previous["id"],
            coverage_mode="question",
            max_calls=2,
        )
        context = projects.context(project["id"], project["steps"][-1], repo)
        prior = next(
            row for row in context["previous_findings"] if row["run_id"] == previous["run_id"]
        )
        assert prior["historical_source_cutoffs"] == [cutoff]
        assert "不是当前岗位事实" in prior["historical_source_note"]
        assert prior["derived_claims"][0]["text"] == original["claims"][0]["text"]
        assert context["reply_to"]["findings_included"]
        assert "historical_reply" not in context
        assert reopened.get(previous["run_id"])["result"] == original
        assert "历史原文读取截止" in render(original)
        assert projects.usage(project)["reserved_calls"] == 3
    finally:
        reopened.close()
