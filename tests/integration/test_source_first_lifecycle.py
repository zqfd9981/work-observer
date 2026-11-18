"""Source-first backup and erasure wiring; synthetic tools, never human quality proof."""

import asyncio
import json
from pathlib import Path

import pytest
from test_source_first_research import SourceModel

from work_observer.config import Settings
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.maintenance import backup_workspace, restore_workspace
from work_observer.memory.lifecycle import forget_personal, pending_erasures
from work_observer.memory.service import MemoryService
from work_observer.quality.research_benchmark import TABLES, ResearchBenchmarkService
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import DIMENSIONS
from work_observer.reports.results import read_result, save_result
from work_observer.research.agent import RESEARCH_METHOD_VERSION, method_fingerprint, research
from work_observer.research.source_first import REQUIRED_FACETS, review_findings
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


def _agent_blind_feedback(packet):
    return {
        "packet_sha256": packet["packet_sha256"],
        "reviewer": "合成工具替身，不是人类审核",
        "reviewer_kind": "agent_assisted",
        "independent_review_declared": False,
        "blinded_review_declared": False,
        "dimensions": {
            key: {"rating": "unknown", "reason": "SYNTHETIC_SOURCE_BLIND_PRIVATE"}
            for key in DIMENSIONS
        },
        "claim_ratings": [
            {
                "index": row["index"],
                "support": "unknown",
                "requirement": "unknown",
                "reason": "SYNTHETIC_SOURCE_BLIND_PRIVATE",
            }
            for row in packet["claims"]
        ],
        "criterion_ratings": [
            {
                "id": row["id"],
                "rating": "unknown",
                "reason": "SYNTHETIC_SOURCE_BLIND_PRIVATE",
            }
            for row in packet["completion_criteria"]
        ],
        "note": "SYNTHETIC_SOURCE_BLIND_PRIVATE",
    }


def test_source_first_ledger_backup_restore_and_actual_memory_erasure(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    database = original / "app.db"
    upgrade(database)
    repo = Repository(database)
    store = ResearchStore(original / "checkpoints.db", str(database.resolve()))
    repo.bind_research_store(store)
    copied_repo = copied_store = None
    try:
        descriptions = {}
        for index, language in enumerate(("Python", "Java")):
            text = f"岗位职责：\n负责{language}接口开发；与平台团队协作。"
            identity = import_jd(
                repo,
                RawArchive(original / "raw"),
                ManualJD(
                    title=f"合成生命周期岗位{index}",
                    company="合成公司",
                    description=text,
                    data_kind="synthetic",
                ),
            )["job_id"]
            descriptions[identity] = text
        jobs = list(descriptions)
        memory = MemoryService(repo).create("preference", "SYNTHETIC_SOURCE_PERSONAL_PRIVATE")
        question = "SYNTHETIC_SOURCE_LIFECYCLE_QUESTION：比较工作任务，保留个人分工未知"
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
        run_id = result["run_id"]
        assert result["status"] == "completed"
        assert memory["id"] in {row["id"] for row in result["memory_used"]}
        assert "SYNTHETIC_SOURCE_PERSONAL_PRIVATE" in json.dumps(store.load_checkpoint(run_id))
        assert result["source_binding_check"]["binding_passed"]
        assert result["source_binding_check"]["semantic_approval"] is False
        assert len(result["source_findings"]) == len(jobs) * len(REQUIRED_FACETS)
        for finding in result["source_findings"]:
            if finding["facet"] == "work_task":
                assert finding["state"] == "stated" and finding["citations"]
                for citation in finding["citations"]:
                    assert (
                        descriptions[finding["job_id"]][citation["start"] : citation["end"]]
                        == citation["text"]
                    )
            else:
                assert finding["state"] == "not_disclosed" and not finding["citations"]
        reports = original / "reports"
        exported = save_result(result, reports)
        store.save(run_id, saved=exported)
        reviews = QualityReviewService(store, repo)
        packet = reviews.packet(run_id)
        quality_review = reviews.submit(
            run_id,
            {
                "result_sha256": packet["result_sha256"],
                "reviewer": "合成Agent工具替身",
                "reviewer_kind": "agent_assisted",
                "decision": "pending",
                "note": "SYNTHETIC_SOURCE_QUALITY_PRIVATE",
                "dimensions": {
                    key: {"rating": "unknown", "reason": "SYNTHETIC_SOURCE_QUALITY_PRIVATE"}
                    for key in DIMENSIONS
                },
                "claim_reviews": [
                    {
                        "index": row["index"],
                        "support": "unknown",
                        "requirement": "unknown",
                        "note": "SYNTHETIC_SOURCE_QUALITY_PRIVATE",
                    }
                    for row in packet["claims"]
                ],
            },
        )
        benchmarks = ResearchBenchmarkService(store, repo)
        protocol = benchmarks.preregister(
            "SYNTHETIC_SOURCE_PROTOCOL_PRIVATE",
            [
                {
                    "id": "D1",
                    "split": "development",
                    "question": question,
                    "job_ids": jobs,
                    "criteria": [
                        {"id": "tasks", "description": "SYNTHETIC_SOURCE_CRITERIA_PRIVATE"}
                    ],
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
            task_author="合成开发者，不是独立人审",
            allow_retrospective_development=True,
        )
        benchmark_id = protocol["id"]
        benchmarks.open_phase(benchmark_id, "development")
        submission = benchmarks.register(benchmark_id, "D1", "candidate", run_id)
        assert not submission["contract_issues"]
        assert memory["id"] in {row["id"] for row in submission["memory_refs"]}
        sealed = benchmarks.seal_phase(benchmark_id, "development", record_missing=True)
        packets = [benchmarks.blind_packet(benchmark_id, key) for key in sealed["packet_ids"]]
        blind = next(packet for packet in packets if packet["claims"])
        assert blind["source_findings"] == review_findings(result["source_findings"])
        blind_review = benchmarks.submit_review(
            benchmark_id, blind["packet_id"], _agent_blind_feedback(blind)
        )
        assert blind_review["reviewer_kind"] == "agent_assisted"

        bundle, restored_root = tmp_path / "bundle", tmp_path / "restored"
        backup_workspace(database, bundle, reports)
        restored = restore_workspace(bundle, restored_root)
        copied_repo = Repository(Path(restored["database"]))
        copied_store = ResearchStore(
            restored_root / "checkpoints.db", str(Path(restored["database"]).resolve())
        )
        copied_repo.bind_research_store(copied_store)
        copied_benchmarks = ResearchBenchmarkService(copied_store, copied_repo)
        copied_run = copied_store.get(run_id)
        assert copied_run["input"]["approach"] == "source_first"
        assert copied_run["result"] == result
        assert copied_run["result"]["research_method_sha256"] == method_fingerprint("source_first")
        assert (
            copied_store.load_checkpoint(run_id)["result"]["source_findings"]
            == result["source_findings"]
        )
        assert copied_benchmarks.blind_packet(benchmark_id, blind["packet_id"]) == blind
        copied_submission = json.loads(
            copied_store.db.execute(
                "SELECT record FROM research_benchmark_submissions WHERE namespace=? AND id=?",
                (copied_store.namespace, submission["id"]),
            ).fetchone()[0]
        )
        assert copied_submission["actual_method"]["approach"] == "source_first"
        assert copied_submission["actual_method"]["method_sha256"] == method_fingerprint(
            "source_first"
        )
        copied_reports = Path(restored["reports_dir"])
        assert (
            read_result(exported["report_id"], copied_reports)["source_findings"]
            == result["source_findings"]
        )
        assert (copied_reports / (exported["report_id"] + ".md")).is_file()
        assert (
            QualityReviewService(copied_store, copied_repo).list_run(run_id)[0]["id"]
            == quality_review["id"]
        )

        for current_repo, current_store, current_reports, current_benchmarks in (
            (repo, store, reports, benchmarks),
            (copied_repo, copied_store, copied_reports, copied_benchmarks),
        ):
            erased = forget_personal(current_repo, current_store, memory["id"], current_reports)
            assert run_id in erased["affected_run_ids"]
            assert benchmark_id in erased["invalidated_research_benchmark_ids"]
            assert quality_review["id"] in erased["invalidated_quality_review_ids"]
            assert pending_erasures(current_store) == 0
            assert current_store.get(run_id)["state"] == "invalidated"
            assert current_store.get(run_id)["result"] is None
            assert current_store.load_checkpoint(run_id) is None
            assert not (current_reports / (exported["report_id"] + ".json")).exists()
            assert not (current_reports / (exported["report_id"] + ".md")).exists()
            with pytest.raises(ProbeError, match="BENCHMARK_DEPENDENCY_FORGOTTEN"):
                current_benchmarks.blind_packet(benchmark_id, blind["packet_id"])
            for table in ("research_checkpoints", "quality_reviews", *TABLES):
                records = [
                    json.loads(row[0])
                    for row in current_store.db.execute(
                        f"SELECT record FROM {table} WHERE namespace=?", (current_store.namespace,)
                    )
                ]
                assert records
                encoded = json.dumps(records, ensure_ascii=False)
                assert "SYNTHETIC_SOURCE_" not in encoded
                assert "source_findings" not in encoded
                assert "合成机制核对，不是真实质量证据" not in encoded
                assert "两份合成岗位分别负责Python与Java接口开发" not in encoded
            assert current_repo.counts()["jobs"] == len(descriptions)
            for job, text in descriptions.items():
                assert current_repo.job(job)["current"]["description_text"] == text
                raw = Catalog(current_repo).evidence(job)
                assert raw[0]["quote"] == text
                assert (
                    Catalog(current_repo).document(raw[0]["document_id"])["integrity"] == "verified"
                )
            if current_store is store:
                assert copied_store.get(run_id)["result"] == result
                assert (copied_reports / (exported["report_id"] + ".json")).is_file()
        # Original erasure never edits this separately held backup; its restored
        # workspace required its own authorized lifecycle call above.
        assert (bundle / "app.db").is_file()
    finally:
        if copied_store:
            copied_store.close()
        if copied_repo:
            copied_repo.close()
        store.close()
        repo.close()
