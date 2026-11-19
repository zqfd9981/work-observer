"""The Agent compares frozen snapshots; history does not bypass current-memory checks."""

import asyncio
import json
from copy import deepcopy

import pytest
from test_source_first_research import source_workspace as source_workspace
from test_work_materials import MaterialModel

from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.connectors.public_documents import PublicDocumentService
from work_observer.memory.service import MemoryService
from work_observer.quality.reviews import QualityReviewService
from work_observer.reports.results import audit_result, render
from work_observer.research.agent import method_fingerprint, research
from work_observer.research.archive_versions import (
    POLICY,
    POLICY_V1,
    VERSION,
    compare,
    historical_evidence_ids,
)
from work_observer.research.archived_sources import POLICY as READER_POLICY


def versions(repo, tmp_path):
    service = PublicDocumentService(repo, tmp_path / "raw")
    first = service.archive_text("合成SOP", "checkpoint检查任务，先核对原文。", "合成说明")[
        "document"
    ]
    second = service.revise_text(
        first["id"], first["title"], "checkpoint检查任务，须经平台负责人复核。"
    )["document"]
    return first["id"], second["id"]


class ComparisonModel:
    def __init__(self, earlier, later, interrupt=False):
        self.earlier, self.later, self.interrupt = earlier, later, interrupt

    async def turn(self, history):
        outputs = [
            json.loads(row["output"])
            for row in history
            if row.get("type") == "function_call_output"
        ]
        if not outputs:
            name, args = (
                "compare_archived_versions",
                {"earlier_id": self.earlier, "later_id": self.later},
            )
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            evidence = outputs[0]["evidence"]
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "text": (
                                "两次保存的粘贴原文分别描述先核对原文和须经平台负责人复核，"
                                "记录了用户改稿。"
                            ),
                            "category": "task",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "evidence_ids": [row["id"] for row in evidence],
                        },
                        {
                            "text": "较晚保存的原文写有平台负责人复核步骤。",
                            "category": "responsibility",
                            "basis": "direct",
                            "requirement": "unspecified",
                            "evidence_ids": [evidence[1]["id"]],
                        },
                    ],
                    "gaps": ["粘贴改稿不证明外部业务实际改变或已经执行。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def run(repo, earlier, later, **options):
    return asyncio.run(
        research(
            repo,
            "比较所选资料版本",
            Settings(),
            job_ids=[],
            public_document_ids=[earlier, later],
            coverage_mode="question",
            max_calls=3,
            model=ComparisonModel(earlier, later),
            **options,
        )
    )


def test_two_call_comparison_has_both_sources_and_history_remains_distinct_from_current_knowledge(
    source_workspace, tmp_path
):
    repo, store, _ = source_workspace
    earlier, later = versions(repo, tmp_path)
    result = run(repo, earlier, later)
    assert result["status"] == "completed" and result["model_calls"] == 2
    assert result["archive_versions_version"] == VERSION
    record = result["archive_comparisons"][0]
    assert record["change_kind"] == "user_text_revision"
    assert {ev["public_document_id"] for ev in result["evidence"]} == {earlier, later}
    assert historical_evidence_ids(repo, result) == {ev["id"] for ev in result["evidence"]}
    assert not audit_result(result, repo)["stale_dependencies"]
    assert "所选归档版本对照" in render(result) and "用户修订正文" in render(result)
    packet = QualityReviewService(store, repo).packet(result["run_id"])
    assert packet["archive_comparisons"] == result["archive_comparisons"]
    # A historical comparison is reviewable. Old source evidence still cannot
    # become current knowledge by saving it from a comparison answer.
    memory = MemoryService(repo)
    old = memory.create(
        "knowledge",
        result["claims"][0]["text"],
        evidence=result["evidence"],
        source_run_id=result["run_id"],
    )
    with pytest.raises(ProbeError, match="STALE|CHANGED"):
        memory.activate(old["id"])
    current = memory.create(
        "knowledge",
        result["claims"][1]["text"],
        evidence=[result["evidence"][1]],
        source_run_id=result["run_id"],
    )
    assert memory.activate(current["id"])["status"] == "active"
    assert (
        method_fingerprint(requirement_guard="qualification-guard-v1")
        == "39a1ac282065db07b44b5c0bc259599ceb2f05a626d0fe478885c43e397dff24"
    )


def test_historical_exception_requires_valid_pair_hash_and_two_sided_scope(
    source_workspace, tmp_path
):
    repo, _, _ = source_workspace
    first, second = versions(repo, tmp_path)
    result = run(repo, first, second)
    for corrupt in ("version", "hash", "scope", "refs"):
        changed = deepcopy(result)
        if corrupt == "version":
            changed.pop("archive_versions_version")
        elif corrupt == "hash":
            changed["archive_comparisons"][0]["earlier"]["sha256"] = "0" * 64
        elif corrupt == "scope":
            changed["scope"]["archived_public_ids"] = [second]
        else:
            changed["archive_comparisons"][0]["evidence_ids"] = [result["evidence"][1]["id"]]
        assert historical_evidence_ids(repo, changed) == set()
        assert audit_result(changed, repo)["stale_dependencies"]


@pytest.mark.parametrize("contract", [VERSION, "archive-versions-v1"])
def test_interrupted_comparison_reopens_with_same_pair_and_remaining_budget(
    source_workspace, tmp_path, contract
):
    repo, store, _ = source_workspace
    first, second = versions(repo, tmp_path)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "比较所选资料版本",
                Settings(),
                job_ids=[],
                public_document_ids=[first, second],
                coverage_mode="question",
                max_calls=3,
                model=ComparisonModel(first, second, True),
            )
        )
    run = store.list()[0]
    frozen = deepcopy(store.load_checkpoint(run["id"]))
    if contract == "archive-versions-v1":
        frozen["result"].pop("archived_sources_version")
        frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(READER_POLICY, "")
        frozen["result"]["archive_versions_version"] = contract
        frozen["result"]["research_method_sha256"] = method_fingerprint(
            coverage_mode="question",
            public_only=True,
            work_materials=True,
            archive_versions=True,
            archive_version=contract,
        )
        frozen["result"]["research_method_version"] = frozen["result"][
            "research_method_version"
        ].replace(VERSION, contract)
        frozen["history"][0]["content"] = frozen["history"][0]["content"].replace(POLICY, POLICY_V1)
        store.checkpoint(run["id"], frozen)
        store.save(run["id"], result=frozen["result"])
    result = asyncio.run(
        research(
            repo,
            run["input"]["question"],
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=ComparisonModel(first, second),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 3
    assert result["archive_versions_version"] == contract
    assert result["archive_comparisons"] == frozen["result"]["archive_comparisons"]
    assert sum(row["tool"] == "compare_archived_versions" for row in result["trace"]) == 1
    assert result["research_method_sha256"] == frozen["result"]["research_method_sha256"]


def test_comparison_cannot_read_an_unselected_document(source_workspace, tmp_path):
    repo, _, _ = source_workspace
    first, second = versions(repo, tmp_path)
    other = PublicDocumentService(repo, tmp_path / "raw").archive_text(
        "合成无关资料", "不可泄露的资料"
    )["document"]["id"]
    result = asyncio.run(
        research(
            repo,
            "比较所选资料版本",
            Settings(),
            job_ids=[],
            public_document_ids=[first, second],
            coverage_mode="question",
            max_calls=2,
            model=ComparisonModel(first, other),
        )
    )
    assert result["status"] == "failed" and result["stop_reason"] == "RESEARCH_SCOPE_VIOLATION"
    assert result["evidence"] == [] and result["archive_comparisons"] == []


def test_pre_feature_checkpoint_keeps_original_method_without_comparison_tool(
    source_workspace, tmp_path
):
    repo, store, _ = source_workspace
    first, second = versions(repo, tmp_path)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "接口",
                Settings(),
                job_ids=[],
                public_document_ids=[first, second],
                coverage_mode="question",
                max_calls=3,
                model=MaterialModel(interrupt=True),
            )
        )
    run = store.list()[0]
    saved = store.load_checkpoint(run["id"])
    baseline = method_fingerprint(coverage_mode="question", public_only=True, work_materials=True)
    saved["result"].pop("archived_sources_version")
    saved["history"][0]["content"] = saved["history"][0]["content"].replace(READER_POLICY, "")
    saved["result"].pop("archive_versions_version")
    saved["result"].pop("archive_comparisons")
    saved["result"]["scope"].pop("archive_version_pairs")
    saved["result"]["research_method_sha256"] = baseline
    saved["history"][0]["content"] = saved["history"][0]["content"].replace(POLICY, "")
    initial = json.loads(saved["history"][1]["content"])
    initial["fixed_scope"].pop("archive_version_pairs")
    saved["history"][1]["content"] = json.dumps(initial)
    store.checkpoint(run["id"], saved)
    result = asyncio.run(
        research(
            repo,
            "接口",
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=MaterialModel(),
        )
    )
    assert result["status"] == "completed" and "archive_versions_version" not in result
    assert result["research_method_sha256"] == baseline and "archive_comparisons" not in result


def test_newer_unselected_version_does_not_leak_into_comparison_metadata(
    source_workspace, tmp_path
):
    repo, _, _ = source_workspace
    first, second = versions(repo, tmp_path)
    before = compare(repo, first, second, [first, second])
    newer = PublicDocumentService(repo, tmp_path / "raw").revise_text(
        second, "合成SOP", "checkpoint检查任务：另有未选变更。"
    )["document"]["id"]
    after = compare(repo, first, second, [first, second])
    assert before == after
    assert newer not in json.dumps(after)
