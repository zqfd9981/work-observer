"""Actual bounded engine/store with synthetic tool outputs; no provider calls."""

import asyncio
import json

import pytest

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import method_fingerprint, research
from work_observer.research.source_first import REQUIRED_FACETS
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def source_workspace(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    store = ResearchStore(tmp_path / "checkpoints.db", str(path.resolve()))
    repo.bind_research_store(store)
    jobs = [
        import_jd(
            repo,
            RawArchive(tmp_path / "raw"),
            ManualJD(
                title=f"合成建设岗位{i}",
                company="合成公司",
                description=f"岗位职责：\n负责{lang}接口开发；与平台团队协作。",
                data_kind="synthetic",
            ),
        )["job_id"]
        for i, lang in enumerate(("Python", "Java"))
    ]
    yield repo, store, jobs
    store.close()
    repo.close()


class SourceModel:
    def __init__(self, *, interrupt=False, bad_sentence=False, unknown_claim=False):
        self.interrupt = interrupt
        self.bad_sentence = bad_sentence
        self.unknown_claim = unknown_claim

    async def turn(self, history):
        outputs = [
            json.loads(item["output"])
            for item in history
            if item.get("type") == "function_call_output"
        ]
        views = next(
            (row["source_view"] for row in reversed(outputs) if "source_view" in row), None
        )
        jobs = outputs[0]["jobs"] if outputs else []
        read = {job["job_id"] for job in (views or {}).get("jobs", [])}
        registered = next((row for row in outputs if row.get("saved")), None)
        if not outputs:
            name, args = "query_jobs", {}
        elif len(read) < len(jobs):
            name, args = "read_job", {"job_id": next(j["id"] for j in jobs if j["id"] not in read)}
        elif not registered:
            findings = []
            for job in views["jobs"]:
                sentence = job["sources"][0]["sentences"][1]
                for facet in sorted(REQUIRED_FACETS):
                    findings.append(
                        {
                            "id": f"F{len(findings) + 1}",
                            "job_id": job["job_id"],
                            "facet": facet,
                            "state": "stated" if facet == "work_task" else "not_disclosed",
                            "sentence_ids": [sentence["sentence_id"]]
                            if facet == "work_task"
                            else [],
                            "supersedes": [],
                            "reason": "合成机制核对，不是真实质量证据",
                        }
                    )
            if self.bad_sentence and not any(row.get("saved") is False for row in outputs):
                next(row for row in findings if row["sentence_ids"])["sentence_ids"] = ["forged"]
            name, args = "record_source_findings", {"findings": findings}
        else:
            if self.interrupt:
                raise asyncio.CancelledError()
            findings = registered["active_findings"]
            keys = [row["id"] for row in findings if row["facet"] == "work_task"]
            if self.unknown_claim and not any(row.get("source_finding_check") for row in outputs):
                keys = [row["id"] for row in findings if row["facet"] == "personal_coding_share"]
            evidence = [job["sources"][0]["sentences"][1]["evidence_id"] for job in views["jobs"]]
            name, args = (
                "finish_research",
                {
                    "claims": [
                        {
                            "category": "task",
                            "basis": "synthesis",
                            "requirement": "unspecified",
                            "text": "两份合成岗位分别负责Python与Java接口开发，均保留团队协作。",
                            "evidence_ids": evidence,
                            "finding_ids": keys,
                        }
                    ],
                    "gaps": ["个人编码份额、独立程度、上线权限分别待核实。"],
                },
            )
        call = {
            "type": "function_call",
            "name": name,
            "arguments": json.dumps(args),
            "call_id": str(len(history)),
        }
        return [call], call


@pytest.mark.parametrize("repair", ["none", "forged_sentence", "unknown_claim"])
def test_candidate_uses_real_read_receipts_repairs_in_budget_and_keeps_default(
    source_workspace, repair
):
    repo, store, jobs = source_workspace
    result = asyncio.run(
        research(
            repo,
            "合成跨岗工作比较",
            Settings(),
            job_ids=jobs,
            approach="source_first",
            max_calls=6,
            model=SourceModel(
                bad_sentence=repair == "forged_sentence", unknown_claim=repair == "unknown_claim"
            ),
        )
    )
    assert result["status"] == "completed"
    assert result["model_calls"] == (5 if repair == "none" else 6)
    assert result["source_binding_check"]["binding_passed"]
    assert not result["source_binding_check"]["semantic_approval"]
    assert len(result["source_findings"]) == 12
    assert all(
        row["state"] == "stated" for row in result["source_findings"] if row["facet"] == "work_task"
    )
    assert store.get(result["run_id"])["input"]["approach"] == "source_first"
    assert result["research_method_sha256"] != method_fingerprint()
    assert (
        store.load_checkpoint(result["run_id"])["result"]["source_findings"]
        == result["source_findings"]
    )
    from work_observer.quality.reviews import QualityReviewService

    packet = QualityReviewService(store, repo).packet(result["run_id"])
    assert len(packet["source_findings"]) == 12
    assert any(row["state"] == "not_disclosed" for row in packet["source_findings"])


def test_interrupted_candidate_resumes_ledger_and_original_budget_without_repeating_registration(
    source_workspace,
):
    repo, store, jobs = source_workspace
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成中断研究",
                Settings(),
                job_ids=jobs,
                approach="source_first",
                max_calls=6,
                model=SourceModel(interrupt=True),
            )
        )
    run = store.list()[0]
    assert run["state"] == "interrupted" and run["result"]["model_calls"] == 5
    before = run["result"]["source_findings"]
    result = asyncio.run(
        research(
            repo,
            run["input"]["question"],
            Settings(),
            checkpoint=(store, run["id"]),
            resume=True,
            model=SourceModel(),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 6
    assert result["source_findings"] == before and result["approach"] == "source_first"
    assert sum(row["tool"] == "record_source_findings" for row in result["trace"]) == 1


def test_candidate_method_change_requires_new_run_and_no_additional_model_attempt(source_workspace):
    repo, store, jobs = source_workspace
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            research(
                repo,
                "合成版本冻结",
                Settings(),
                job_ids=jobs,
                approach="source_first",
                max_calls=6,
                model=SourceModel(interrupt=True),
            )
        )
    run = store.list()[0]
    checkpoint = store.load_checkpoint(run["id"])
    checkpoint["result"]["research_method_sha256"] = "0" * 64
    store.checkpoint(run["id"], checkpoint)
    with pytest.raises(ProbeError, match="METHOD_CHANGED"):
        asyncio.run(
            research(
                repo,
                run["input"]["question"],
                Settings(),
                checkpoint=(store, run["id"]),
                resume=True,
                model=SourceModel(),
            )
        )
    assert store.load_checkpoint(run["id"])["result"]["model_calls"] == 5


def test_candidate_does_not_silently_enable_public_search(source_workspace):
    repo, store, jobs = source_workspace
    with pytest.raises(ProbeError, match="LOCAL_JD_ONLY"):
        asyncio.run(
            research(
                repo,
                "合成范围",
                Settings(),
                job_ids=jobs,
                approach="source_first",
                allow_public=True,
                model=SourceModel(),
            )
        )
    assert not store.list()


def test_long_body_requires_actual_followup_window_before_not_disclosed(source_workspace, tmp_path):
    repo, store, _ = source_workspace
    text = "岗位职责：\n负责Python接口开发；" + ("\n补充材料：" + "说明" * 400 + "。") * 8
    job = import_jd(
        repo,
        RawArchive(tmp_path / "long-raw"),
        ManualJD(title="合成长正文", company="合成公司", description=text, data_kind="synthetic"),
    )["job_id"]

    class WindowModel(SourceModel):
        async def turn(self, history):
            outputs = [
                json.loads(item["output"])
                for item in history
                if item.get("type") == "function_call_output"
            ]
            views = next(
                (row["source_view"] for row in reversed(outputs) if "source_view" in row), None
            )
            if views:
                source = views["jobs"][0]["sources"][0]
                if source["coverage"]["gaps"]:
                    call = {
                        "type": "function_call",
                        "name": "read_source_window",
                        "arguments": json.dumps(
                            {"job_id": job, "start": source["coverage"]["gaps"][0]["start"]}
                        ),
                        "call_id": str(len(history)),
                    }
                    return [call], call
            result, call = await super().turn(history)
            if call["name"] == "finish_research":
                args = json.loads(call["arguments"])
                args["claims"][0]["text"] = "合成长正文岗位负责Python接口开发，个人权限仍需核实。"
                call["arguments"] = json.dumps(args)
            return result, call

    result = asyncio.run(
        research(
            repo,
            "合成长正文阅读凭据",
            Settings(),
            job_ids=[job],
            approach="source_first",
            model=WindowModel(),
            max_calls=5,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 5
    assert sum(row["tool"] == "read_source_window" for row in result["trace"]) == 1
    saved = store.load_checkpoint(result["run_id"])
    receipts = [
        json.loads(item["output"])["source_view"]
        for item in saved["history"]
        if item.get("type") == "function_call_output"
        and "source_view" in json.loads(item["output"])
    ]
    assert not receipts[0]["jobs"][0]["sources"][0]["coverage"]["fully_read"]
    assert receipts[-1]["jobs"][0]["sources"][0]["coverage"]["fully_read"]
    assert any(row["state"] == "not_disclosed" for row in result["source_findings"])


def test_benchmark_pins_approach_and_keeps_the_complete_ledger_in_anonymous_packet(
    source_workspace,
):
    from work_observer.quality.research_benchmark import ResearchBenchmarkService
    from work_observer.research.agent import RESEARCH_METHOD_VERSION

    repo, store, jobs = source_workspace
    service = ResearchBenchmarkService(store, repo)
    question = "合成锁定职责比较"
    protocol = service.preregister(
        "合成分项方法合同",
        [
            {
                "id": "D1",
                "split": "development",
                "question": question,
                "job_ids": jobs,
                "criteria": [{"id": "work", "description": "保留明示任务与未知分工"}],
                "max_model_calls": 6,
            }
        ],
        {
            arm: {
                "approach": approach,
                "method_sha256": method_fingerprint(approach),
                "method_version": RESEARCH_METHOD_VERSION
                if approach == "standard"
                else "source-first-v1",
            }
            for arm, approach in (("baseline", "standard"), ("candidate", "source_first"))
        },
        task_author="合成测试作者",
    )
    service.open_phase(protocol["id"], "development")
    result = asyncio.run(
        research(
            repo,
            question,
            Settings(),
            job_ids=jobs,
            approach="source_first",
            max_calls=6,
            model=SourceModel(),
        )
    )
    right = service.register(protocol["id"], "D1", "candidate", result["run_id"])
    assert not right["contract_issues"]
    wrong = service.register(protocol["id"], "D1", "baseline", result["run_id"])
    assert "method_contract_mismatch:approach" in wrong["contract_issues"]
    sealed = service.seal_phase(protocol["id"], "development")
    packets = [service.blind_packet(protocol["id"], key) for key in sealed["packet_ids"]]
    assert all(len(packet["source_findings"]) == 12 for packet in packets)
    assert all(
        "approach" not in packet and "research_method_sha256" not in packet for packet in packets
    )
