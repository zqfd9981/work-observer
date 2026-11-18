"""Synthetic findings verify actual report/browser rendering, not research semantics."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.reports.results import read_result, render, save_result
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
            },
            {
                "id": "F4",
                "job_id": job_id,
                "facet": "release_authority",
                "state": "unresolved",
                "active": True,
                "citations": [],
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
