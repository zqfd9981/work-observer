"""Bounded synthetic tool flow verifies map persistence, recovery and review gates."""

import asyncio
import json
from copy import deepcopy

import pytest
from jsonschema import validate
from test_source_first_research import source_workspace as source_workspace

from work_observer.config import Settings
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.reports.results import read_result, render, save_result
from work_observer.research.agent import TOOLS, method_fingerprint, research
from work_observer.research.cognition import VERSION, tools


class MapModel:
    def __init__(self, *, interrupt=False, bad_reference=False):
        self.interrupt = interrupt
        self.bad_reference = bad_reference

    async def turn(self, history):
        outputs = [
            json.loads(r["output"]) for r in history if r.get("type") == "function_call_output"
        ]
        jobs = outputs[0]["jobs"] if outputs else []
        evidence = [ev for row in outputs for ev in row.get("evidence", [])]
        read = {e["job_id"] for e in evidence}
        if not outputs:
            name, args = "query_jobs", {}
        elif len(read) < len(jobs):
            name, args = "read_job", {"job_id": next(j["id"] for j in jobs if j["id"] not in read)}
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            bad = self.bad_reference and not any(row.get("work_map_error") for row in outputs)
            claims = [
                {
                    "category": "task",
                    "basis": "direct",
                    "requirement": "unspecified",
                    "text": "合成接口开发任务",
                    "evidence_ids": [e["citation_key"]],
                }
                for e in evidence
            ]
            name, args = (
                "finish_research",
                {
                    "claims": claims,
                    "gaps": ["独立交付和迁移范围待核实"],
                    "revisions": [],
                    "work_map": {
                        "version": VERSION,
                        "scope_note": "合成有限样本，不是行业分布",
                        "work_types": [
                            {
                                "name": "接口交付",
                                "problem": "开发接口",
                                "tasks": "实现接口并协作",
                                "deliverables": "接口服务",
                                "claim_indices": [99] if bad else [0, 1],
                                "basis": "synthesis",
                                "boundary": "接口任务不证明独立交付整个平台",
                                "next_check": "核实个人分工",
                            }
                        ],
                        "ability_relations": [],
                        "unknowns": ["个人责任和资格未知"],
                    },
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


def test_finish_contract_is_strict_and_does_not_mutate_standard():
    original = deepcopy(TOOLS)
    contract = tools(TOOLS)[-1]["parameters"]
    assert set(contract["required"]) == {"claims", "gaps", "work_map", "revisions"}
    for definition in contract["$defs"].values():
        if definition.get("type") == "object":
            assert set(definition["required"]) == set(definition["properties"])
            assert definition["additionalProperties"] is False
    assert TOOLS == original
    assert method_fingerprint("work_map") != method_fingerprint()


@pytest.mark.parametrize("repair", [False, True])
def test_map_engine_saves_original_references_and_repairs_within_budget(
    source_workspace, tmp_path, repair
):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成工作地图",
            Settings(),
            job_ids=jobs,
            approach="work_map",
            max_calls=5,
            model=MapModel(bad_reference=repair),
        )
    )
    assert result["status"] == "completed"
    assert result["model_calls"] == (5 if repair else 4)
    assert result["analysis_origin"] == "research_agent"
    assert result["work_map"]["version"] == VERSION
    assert result["research_method_sha256"] == method_fingerprint("work_map")
    assert store.get(result["run_id"])["input"]["approach"] == "work_map"
    assert store.load_checkpoint(result["run_id"])["result"]["work_map"] == result["work_map"]
    assert all(
        c["evidence_ids"][0] in {e["id"] for e in result["evidence"]} for c in result["claims"]
    )
    saved = save_result(result, tmp_path / "reports")
    loaded = read_result(saved["report_id"], tmp_path / "reports")
    assert loaded["work_map"] == result["work_map"]
    assert "## 工作类型地图" in render(loaded)
    assert "开发分析样稿" not in render(loaded)
    validate(
        {
            "claims": result["claims"],
            "gaps": result["gaps"],
            "work_map": result["work_map"],
            "revisions": [],
        },
        tools(TOOLS)[-1]["parameters"],
    )


def test_map_resume_keeps_method_and_consumed_budget(source_workspace):
    repo, store, jobs = source_workspace
    run = store.create({"question": "合成工作地图", "approach": "work_map"})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成工作地图",
                Settings(),
                job_ids=jobs,
                approach="work_map",
                max_calls=6,
                model=MapModel(interrupt=True),
                checkpoint=(store, run["id"]),
            )
        )
    assert store.load_checkpoint(run["id"])["result"]["model_calls"] == 4
    result = asyncio.run(
        research(
            repo,
            "合成工作地图",
            Settings(),
            resume=True,
            checkpoint=(store, run["id"]),
            model=MapModel(),
        )
    )
    assert result["approach"] == "work_map"
    assert result["model_calls"] == 5
    assert [row["tool"] for row in result["trace"]].count("query_jobs") == 1


def test_changed_map_contract_cannot_resume_old_run(source_workspace, monkeypatch):
    repo, store, jobs = source_workspace
    run = store.create({"question": "合成工作地图", "approach": "work_map"})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成工作地图",
                Settings(),
                job_ids=jobs,
                approach="work_map",
                max_calls=6,
                model=MapModel(interrupt=True),
                checkpoint=(store, run["id"]),
            )
        )
    original = store.load_checkpoint(run["id"])
    monkeypatch.setattr("work_observer.research.cognition.POLICY", "Changed synthetic contract")
    with pytest.raises(ProbeError, match="RESEARCH_METHOD_CHANGED_NEW_RUN_REQUIRED"):
        asyncio.run(
            research(
                repo,
                "合成工作地图",
                Settings(),
                resume=True,
                checkpoint=(store, run["id"]),
                model=MapModel(),
            )
        )
    assert store.load_checkpoint(run["id"]) == original


def test_map_review_cannot_approve_only_the_underlying_claims(source_workspace):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成工作地图",
            Settings(),
            job_ids=jobs,
            approach="work_map",
            max_calls=5,
            model=MapModel(),
        )
    )
    service = QualityReviewService(store, repo)
    packet = service.packet(result["run_id"])
    assert packet["work_map"] == result["work_map"]
    review = dict(
        result_sha256=packet["result_sha256"],
        reviewer="合成人审机制测试",
        reviewer_kind="human",
        decision="approve",
        note="仅合成机制验收",
        dimensions={key: {"rating": "pass", "reason": "合成测试"} for key in DIMENSIONS},
        claim_reviews=[
            dict(index=i, support="supported", requirement="correct", note="合成原文支持")
            for i in range(len(packet["claims"]))
        ],
    )
    with pytest.raises(ProbeError, match="QUALITY_WORK_MAP_REVIEW_REQUIRED"):
        service.submit(result["run_id"], review)
    review["work_map_review"] = {"rating": "pass", "reason": "合成分组边界及全部关系核对"}
    assert service.submit(result["run_id"], review)["status"] == "approved"
