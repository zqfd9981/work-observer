"""Report-local references must remain usable and keep analysis provenance explicit."""

import json
from copy import deepcopy

import pytest

from work_observer.reports.cognition import checked_map, render_map
from work_observer.reports.results import read_result, render, save_result


def sample():
    return {
        "question": "合成工作地图",
        "created_at": "2026-11-19T00:00:00Z",
        "status": "analysis_draft",
        "analysis_origin": "developer_sample",
        "scope": {
            "counts": {"scope_total": 0, "matched": 0, "unknown": 0, "candidate_details": 0},
            "jobs": [],
        },
        "evidence": [
            {
                "id": "e1",
                "source": "public_web",
                "title": "合成原文",
                "url": "https://example.test",
                "observed_at": "2026-11-19",
                "quote": "合成材料",
            }
        ],
        "claims": [
            {
                "category": "task",
                "requirement": "unspecified",
                "text": "合成任务",
                "evidence_ids": ["e1"],
            }
        ],
        "gaps": ["待核对"],
        "work_map": {
            "version": "synthetic-v1",
            "scope_note": "合成测试，不是行业分布",
            "work_types": [
                {
                    "name": "合成类型",
                    "problem": "问题",
                    "tasks": "任务",
                    "deliverables": "交付物",
                    "claim_indices": [0],
                    "boundary": "不代表纯配置",
                    "next_check": "核实分工",
                }
            ],
            "ability_relations": [
                {
                    "task": "任务",
                    "ability": "能力",
                    "rationale": "解释",
                    "claim_indices": [0],
                    "transfer_limit": "要求性质未知",
                }
            ],
            "unknowns": ["混合与缺正文保留"],
        },
    }


def test_roundtrip_keeps_origin_evidence_and_map_in_export(tmp_path):
    result = sample()
    saved = save_result(result, tmp_path)
    loaded = read_result(saved["report_id"], tmp_path)
    assert loaded["analysis_origin"] == "developer_sample"
    assert loaded["work_map"] == result["work_map"]
    markdown = render(loaded)
    assert "非产品Agent运行，非独立人审" in markdown
    assert "## 样稿判断（开发分析，待核对）" in markdown
    assert "边界与反例：不代表纯配置" in markdown
    assert "迁移边界：要求性质未知" in markdown
    assert "[E1](#e1)" in markdown


def test_application_background_is_readable_without_changing_saved_result():
    result = sample()
    result["memory_used"] = [
        {
            "kind": "preference",
            "version": 2,
            "content": "个人应用背景（用户自述，结构化）：\n"
            + json.dumps({"background": "合成经历", "goal": "合成新目标", "constraints": ""}),
        }
    ]
    before = deepcopy(result)
    markdown = render(result)
    assert "已有经历或能力：合成经历" in markdown
    assert "本次目标：合成新目标" in markdown
    assert "投入与限制：未说明，不作假设" in markdown
    assert '"background"' not in markdown
    assert result == before


@pytest.mark.parametrize("index", [-1, 1, 999])
def test_invalid_claim_never_writes_partial_report(tmp_path, index):
    result = sample()
    result["work_map"]["work_types"][0]["claim_indices"] = [index]
    with pytest.raises(ValueError, match="不存在的判断"):
        save_result(result, tmp_path)
    assert not list(tmp_path.iterdir())


def test_missing_evidence_rejected_and_legacy_reports_unchanged():
    result = sample()
    before = deepcopy(result)
    checked_map(result)
    assert before == result
    result["claims"][0]["evidence_ids"] = ["missing"]
    with pytest.raises(ValueError, match="缺少可回查原文"):
        checked_map(result)
    assert render_map({"claims": []}, {}) == []


def test_unknown_work_does_not_force_a_type_and_indices_cannot_be_boolean():
    result = sample()
    result["work_map"]["work_types"] = []
    result["work_map"]["ability_relations"] = []
    assert checked_map(result)["work_types"] == []
    result = sample()
    result["work_map"]["work_types"][0]["claim_indices"] = [False]
    with pytest.raises(ValueError):
        checked_map(result)
