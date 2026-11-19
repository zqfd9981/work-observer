"""Synthetic findings verify actual report/browser rendering, not research semantics."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.quality.research_benchmark import ResearchBenchmarkService
from work_observer.quality.reviews import QualityReviewService
from work_observer.quality.service import digest
from work_observer.reports.results import read_result, render, save_result, source_analysis_notes
from work_observer.research.store import ResearchStore
from work_observer.retrieval.catalog import Catalog
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository


@pytest.fixture
def synthetic_result(tmp_path):
    path = tmp_path / "app.db"
    upgrade(path)
    repo = Repository(path)
    job_id = import_jd(
        repo,
        RawArchive(tmp_path / "raw"),
        ManualJD(
            title="合成建设岗位",
            company="合成公司",
            data_kind="synthetic",
            description="岗位做什么：😀搭建 <script>平台</script>。个人分工待核。",
        ),
    )["job_id"]
    evidence = Catalog(repo).evidence(job_id)
    text = "搭建 <script>平台</script>。"
    start = evidence[0]["quote"].index(text)
    finding = {
        "id": "F2",
        "job_id": job_id,
        "facet": "work_task",
        "state": "stated",
        "active": True,
        "supersedes": ["F1"],
        "reason": "修订说明为研究登记，非审核结论",
        "citations": [
            {
                "evidence_id": evidence[0]["id"],
                "snapshot_id": evidence[0]["snapshot_id"],
                "start": start,
                "end": start + len(text),
                "text": text,
            }
        ],
    }
    result = {
        "question": "合成展示问题",
        "created_at": "2026-11-19T00:00:00Z",
        "status": "completed",
        "mode": "synthetic_test_double",
        "approach": "source_first",
        "scope": Catalog(repo).query(job_ids=[job_id]),
        "evidence": evidence,
        "claims": [
            {
                "category": "task",
                "requirement": "unspecified",
                "basis": "direct",
                "text": "合成模型分析",
                "evidence_ids": [evidence[0]["id"]],
            }
        ],
        "gaps": [],
        "source_findings": [
            {**finding, "id": "F1", "active": False, "superseded_by": "F2", "supersedes": []},
            finding,
            {
                "id": "F3",
                "job_id": job_id,
                "facet": "personal_coding_share",
                "state": "not_disclosed",
                "active": True,
                "citations": [],
                "reason": "合成正文未披露个人编码份额",
            },
            {
                "id": "F4",
                "job_id": job_id,
                "facet": "release_authority",
                "state": "unresolved",
                "active": True,
                "citations": [],
                "reason": "合成上线权限仍待核实",
            },
        ],
    }
    yield result
    repo.close()


def test_saved_report_preserves_active_unknown_and_revision_summary(synthetic_result, tmp_path):
    saved = save_result(synthetic_result, tmp_path / "reports")
    restored = read_result(saved["report_id"], tmp_path / "reports")
    assert restored["source_findings"] == synthetic_result["source_findings"]
    text = Path(saved["markdown"]).read_text(encoding="utf-8")
    assert text.index("## 原文分项记录") < text.index("## 判断（模型分析）")
    assert "搭建 <script>平台</script>。" in text
    assert "个人编码分工：已读归档正文中未披露（待核实）" in text
    assert "上线决策与责任：尚不能判断（待核实）" in text
    assert "F1 → F2" in text and "修订说明为研究登记" in text
    assert "[E1](#e1)；原文字符" in text
    assert "不是人工审核通过" in text and "不能覆盖上述原文动作" in text


def test_partial_unit_warning_does_not_rewrite_a_legacy_report_source(synthetic_result):
    row = next(
        row for row in synthetic_result["source_findings"] if row["active"] and row.get("citations")
    )
    cite = row["citations"][0]
    cite.update(
        unit_id="synthetic-partial",
        unit_start=cite["start"],
        unit_end=cite["end"] + 4,
        unit_complete_read=True,
        unit_all_parts_shown=True,
    )
    before = deepcopy(synthetic_result)
    text = render(synthetic_result)
    assert "部分原文单元未完整引用" in text
    assert "后文可能含优先、否定或范围限定" in text
    assert cite["text"] in text
    assert synthetic_result == before
    assert "source_quote_check" not in row


def test_old_report_does_not_acquire_trial_sections(synthetic_result):
    legacy = deepcopy(synthetic_result)
    del legacy["source_findings"]
    text = render(legacy)
    assert "## 判断（模型分析）" in text and "合成模型分析" in text
    assert "原文分项记录" not in text and "分项修订记录" not in text


def test_actual_javascript_selection_rendering_and_unicode_citation(synthetic_result, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; report coverage still runs")
    payload = tmp_path / "synthetic.json"
    payload.write_text(json.dumps(synthetic_result, ensure_ascii=False), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    script = root / "src/work_observer/api/assets/app.js"
    harness = root / "tests/unit/source_first_display.cjs"
    subprocess.run([node, "--check", str(script)], check=True, capture_output=True, text=True)
    outcome = subprocess.run(
        [node, str(harness), str(script), str(payload)], capture_output=True, text=True
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr


@pytest.fixture
def v2_result(synthetic_result):
    result = deepcopy(synthetic_result)
    original, current = result["source_findings"][:2]
    original.update(actor="unspecified", facet="independent_delivery", reason="原登记需纠正")
    current.update(actor="job_holder", reason="保留原句，纠正为岗位建设任务")
    job_id = current["job_id"]
    for identity, facet, actor in (
        ("F5", "task_independence", "job_holder"),
        ("F6", "team_collaboration", "team"),
        ("F7", "execution_safety", "system"),
    ):
        result["source_findings"].append(
            dict(
                id=identity,
                job_id=job_id,
                facet=facet,
                actor=actor,
                state="unresolved",
                active=True,
                citations=[],
                reason="合成展示，不代表语义已核对",
            )
        )
    citation = {
        **current["citations"][0],
        "job_id": job_id,
        "sentence_id": "S-完整限定句",
        "finding_id": current["id"],
        "facet": current["facet"],
        "actor": current["actor"],
        "context": [{"text": "岗位做什么：<em>完整上下文</em>", "start": 0, "end": 8}],
    }
    result["claims"][0].update(
        bindings=[{"finding_id": "F2", "sentence_ids": [citation["sentence_id"]]}],
        sentence_citations=[citation],
    )
    # Selecting no unknown must not hide any active unknown from display/review.
    result["unknown_finding_ids"] = []
    return result


def test_v2_report_actors_facets_precise_support_and_reclassification(v2_result):
    text = render(v2_result)
    assert "主体：招聘岗位承担者" in text and "主体：团队" in text
    assert "原文明示的独立子任务" in text and "执行安全与技术隔离" in text
    assert "更正后维度：岗位建设与工作任务；主体：招聘岗位承担者" in text
    assert "独立端到端负责程度；主体：主体未明确" in text
    assert "原登记所引分句" in text and "原登记需纠正" in text
    assert "已声明的支持子集（不保证语义支持" in text
    assert "S-完整限定句" in text and "&lt;em&gt;完整上下文&lt;/em&gt;" in text
    assert "&lt;script&gt;平台&lt;/script&gt;" in text
    unsafe = deepcopy(v2_result)
    unsafe["source_findings"][-1].update(actor="<script>主体</script>", facet="<img src=x>")
    text = render(unsafe)
    assert "主体：&lt;script&gt;主体&lt;/script&gt;" in text
    assert "&lt;img src=x&gt;" in text


def _blind_display_packet(result):
    """Exercise the production formatter with sealed-source/binding dependencies stubbed."""
    service = object.__new__(ResearchBenchmarkService)
    evidence = result["evidence"][0]
    task = {
        "id": "T",
        "question": result["question"],
        "job_ids": [evidence["job_id"]],
        "criteria": [],
        "max_model_calls": 8,
        "max_elapsed_seconds": 240,
    }
    frozen = {
        "job_id": evidence["job_id"],
        "title": evidence["title"],
        "snapshot_id": evidence["snapshot_id"],
        "document_id": evidence["document_id"],
        "document_sha256": evidence.get("document_sha256"),
        "text": evidence["quote"],
        "data_kind": "synthetic",
    }
    service._protocol = lambda _: (
        {"protocol": {"tasks": [task]}, "protocol_sha256": "a" * 64},
        {"documents": [frozen]},
    )
    service._packet_location = lambda *_: ({"state": "reviewing"}, {"submission_id": "S"})
    service._get = lambda *_: {
        "task_id": "T",
        "execution_status": "completed",
        "contract_issues": [],
    }
    service._bound_result = lambda _: deepcopy(result)
    service._current_issues = lambda _: []
    return service.blind_packet("P", "opaque"), frozen


def test_legacy_blind_packet_has_exact_old_shape_and_hash(synthetic_result):
    from work_observer.research.source_first import review_findings

    packet, frozen = _blind_display_packet(synthetic_result)
    claim = synthetic_result["claims"][0]
    evidence = synthetic_result["evidence"][0]
    expected = {
        "packet_id": "opaque",
        "protocol_sha256": "a" * 64,
        "question": synthetic_result["question"],
        "completion_criteria": [],
        "declared_budget": {"max_model_calls": 8, "max_elapsed_seconds": 240},
        "claims": [
            {
                "index": 0,
                "text": claim["text"],
                "category": claim["category"],
                "basis": claim["basis"],
                "requirement": claim["requirement"],
                "citations": [
                    {
                        k: evidence.get(k)
                        for k in (
                            "id",
                            "job_id",
                            "snapshot_id",
                            "document_id",
                            "document_sha256",
                            "quote",
                            "start",
                            "end",
                        )
                    }
                ],
            }
        ],
        "gaps": [],
        "execution_status": "completed",
        "mechanical_issues": [],
        "frozen_sources": [frozen],
        "notice": "只按冻结原文和完成条件核对，不参考旧评分。字段不暴露arm/run/方法身份；"
        "元数据隐藏不保证审核者此前未见过答案。",
        "source_findings": review_findings(synthetic_result["source_findings"]),
    }
    expected["packet_sha256"] = digest(expected)
    assert packet == expected
    assert "actor" not in json.dumps(packet)
    assert "bindings" not in packet["claims"][0]
    assert "sentence_citations" not in packet["claims"][0]
    assert "source_finding_history" not in packet
    assert "analysis_notes" not in packet
    assert "主体：" not in render(synthetic_result)


def _analysis_notes(result):
    return [
        {
            "index": 0,
            "sides": [
                {
                    "finding_id": "F2",
                    "job_id": result["scope"]["jobs"][0]["id"],
                    "facet": "work_task",
                    "actor": "job_holder",
                },
                {
                    "finding_id": "F8",
                    "job_id": "synthetic-peer-job",
                    "facet": "team_collaboration",
                    "actor": "team",
                },
            ],
            "notice": "多维分析，不表示同口径单维可比；仍须语义核对",
        }
    ]


@pytest.mark.parametrize("note_mode", ["absent", "empty", "top", "nested"])
def test_v2_both_review_packets_keep_support_history_and_all_unknown(
    v2_result, tmp_path, note_mode
):
    result = deepcopy(v2_result)
    result.update(approach="DO_NOT_SHOW_METHOD", research_method_sha256="SECRET_METHOD")
    notes = _analysis_notes(result) if note_mode in {"top", "nested"} else []
    if note_mode == "top":
        result["analysis_notes"] = notes
    elif note_mode == "nested":
        result["source_binding_check"] = {"analysis_notes": notes}
    elif note_mode == "empty":
        result.update(analysis_notes=[], source_binding_check={"analysis_notes": []})
    blind, _ = _blind_display_packet(result)
    text = render(result)
    if notes:
        assert blind["analysis_notes"] == notes
        assert "不表示同口径单维可比，也不表示语义通过" in text
        assert "synthetic-peer-job" in text and "团队协作；主体：团队" in text
        assert "岗位建设与工作任务；主体：招聘岗位承担者" in text
        unsafe = deepcopy(result)
        (unsafe.get("analysis_notes") or unsafe["source_binding_check"]["analysis_notes"])[0][
            "notice"
        ] = "<script>提示</script>"
        assert "&lt;script&gt;提示&lt;/script&gt;" in render(unsafe)
    else:
        assert "analysis_notes" not in blind
        assert "多维分析提示" not in text
        assert blind["packet_sha256"] == _blind_display_packet(v2_result)[0]["packet_sha256"]
    assert blind["claims"][0]["bindings"] == result["claims"][0]["bindings"]
    assert blind["claims"][0]["sentence_citations"] == result["claims"][0]["sentence_citations"]
    assert blind["source_finding_history"][0]["actor"] == "unspecified"
    assert blind["source_finding_history"][0]["facet"] == "independent_delivery"
    assert {r["id"] for r in blind["source_findings"]} >= {"F3", "F4", "F5", "F6", "F7"}
    assert "SECRET_METHOD" not in json.dumps(blind) and "DO_NOT_SHOW_METHOD" not in json.dumps(
        blind
    )
    repo = Repository(tmp_path / "app.db")
    store = ResearchStore(tmp_path / "display-checkpoints.db", str(repo.engine.url.database))
    try:
        run = store.create({"question": result["question"]})
        store.save(run["id"], state="finished", result=result)
        ordinary = QualityReviewService(store, repo).packet(run["id"])
        assert ordinary["claims"][0]["bindings"] == result["claims"][0]["bindings"]
        assert (
            ordinary["claims"][0]["sentence_citations"] == result["claims"][0]["sentence_citations"]
        )
        assert ordinary["source_finding_history"] == blind["source_finding_history"]
        assert ordinary["source_findings"] == blind["source_findings"]
        if notes:
            assert ordinary["analysis_notes"] == notes
        else:
            assert "analysis_notes" not in ordinary
    finally:
        store.close()
        repo.close()


@pytest.mark.parametrize("nested_notes", [False, True])
def test_v2_actual_browser_support_and_complete_qualifier(v2_result, tmp_path, nested_notes):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    result = deepcopy(v2_result)
    if nested_notes:
        result["source_binding_check"] = {"analysis_notes": _analysis_notes(result)}
    else:
        result["analysis_notes"] = _analysis_notes(result)
    # A renderer must not clip a resolver-provided complete unit at the old 700-char edge.
    result["claims"][0]["sentence_citations"][0]["text"] = (
        "熟悉容器化、消息队列、任务调度系统者优先；"
    )
    payload = tmp_path / "v2-display.json"
    payload.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    outcome = subprocess.run(
        [
            node,
            str(root / "tests/unit/source_first_display.cjs"),
            str(root / "src/work_observer/api/assets/app.js"),
            str(payload),
        ],
        capture_output=True,
        text=True,
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr


def test_standard_anonymous_scope_context_without_findings_or_support():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    root = Path(__file__).resolve().parents[2]
    outcome = subprocess.run(
        [
            node,
            str(root / "tests/unit/review_scope_context.cjs"),
            str(root / "src/work_observer/api/assets/app.js"),
        ],
        capture_output=True,
        text=True,
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr


@pytest.mark.parametrize("empty_claims", [False, True])
def test_analysis_notes_only_reference_published_claims(v2_result, empty_claims):
    result = deepcopy(v2_result)
    if empty_claims:
        result["claims"] = []
    valid = _analysis_notes(result)[0]
    invalid = [{**valid, "index": index} for index in (True, False, "0", None, -1, 1, 0.5)]
    result["source_binding_check"] = {"analysis_notes": [*invalid, valid]}
    assert source_analysis_notes(result) == ([] if empty_claims else [valid])
    blind, _ = _blind_display_packet(result)
    if empty_claims:
        assert "analysis_notes" not in blind
    else:
        assert blind["analysis_notes"] == [valid]
