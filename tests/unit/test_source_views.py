"""Literal source localization, independent of models, stores or semantic labels."""

import pytest

from work_observer.research.source_views import build_source_views


def evidence(text, *, start=0, end=None, identity="e1", job="j1", snapshot="s1", **extra):
    end = len(text) if end is None else end
    return {
        "id": identity,
        "job_id": job,
        "snapshot_id": snapshot,
        "quote": text[start:end],
        "start": start,
        "end": end,
        "full_text_length": len(text),
        **extra,
    }


def source(view, job_index=0, source_index=0):
    return view["jobs"][job_index]["sources"][source_index]


def test_exact_unicode_numbering_negative_and_building_sentences_are_not_classified():
    text = (
        "  工作方向：\r\n１．搭建 Agent 平台；不负责训练模型。\n"
        "2. 不要求自研工具；使用现有工具即可。"
    )
    view = build_source_views([evidence(text)])
    item = source(view)
    assert item["coverage"]["fully_read"] and item["all_sentences_shown"]
    sentences = item["sentences"]
    assert "".join(row["text"] for row in sentences) == text
    assert any(row["text"] == "不负责训练模型。\n" for row in sentences)
    assert any("１．搭建 Agent 平台；" in row["text"] for row in sentences)
    assert any("2. 不要求自研工具；" in row["text"] for row in sentences)
    for row in sentences:
        assert text[row["start"] : row["end"]] == row["text"]
        assert row["evidence_id"] == "e1"
        assert not {"category", "requirement", "negation", "responsibility"}.intersection(row)
    assert sentences[0]["heading_heuristic"]
    assert sentences[1]["context"][0]["text"] == "  工作方向：\r\n"
    assert "不推断" in item["context_notice"]
    assert view == build_source_views([evidence(text)])


def test_nested_heading_direction_and_switch_keep_only_read_context():
    text = "# 业务方向\n方向一：平台建设\n1. 搭建工具。\n方向二：配置实施\n2. 配置系统。"
    sentences = source(build_source_views([evidence(text)]))["sentences"]
    first = next(row for row in sentences if "1. 搭建" in row["text"])
    second = next(row for row in sentences if "2. 配置" in row["text"])
    assert [row["text"].strip() for row in first["context"]] == ["# 业务方向", "方向一：平台建设"]
    assert [row["text"].strip() for row in second["context"]] == ["# 业务方向", "方向二：配置实施"]
    for row in second["context"]:
        assert text[row["start"] : row["end"]] == row["text"]


def test_overlap_is_counted_once_and_sentence_spanning_evidence_keeps_valid_quote():
    text = "岗位职责：\n搭建平台并维护服务。交付接口。"
    rows = [evidence(text, end=13), evidence(text, start=9, identity="e2")]
    item = source(build_source_views(rows))
    assert item["coverage"] == {
        "intervals": [{"start": 0, "end": len(text)}],
        "read_chars": len(text),
        "full_text_length": len(text),
        "gaps": [],
        "fully_read": True,
    }
    by_id = {row["id"]: row for row in rows}
    for sentence in item["sentences"]:
        original = by_id[sentence["evidence_id"]]
        assert original["start"] <= sentence["start"] < sentence["end"] <= original["end"]
        assert (
            original["quote"][
                sentence["start"] - original["start"] : sentence["end"] - original["start"]
            ]
            == sentence["text"]
        )
    assert "".join(row["text"] for row in item["sentences"]) == text
    assert any(row["evidence_boundary_end"] for row in item["sentences"])


def test_search_top_k_gaps_and_mid_sentence_boundaries_do_not_claim_full_reading():
    text = "方向一：平台建设\n搭建工具并负责维护；方向二：业务应用\n开发接口。"
    later = text.index("开发")
    rows = [evidence(text, start=13, end=17), evidence(text, start=later, identity="e2")]
    item = source(build_source_views(rows))
    assert not item["coverage"]["fully_read"]
    assert item["coverage"]["gaps"] == [{"start": 0, "end": 13}, {"start": 17, "end": later}]
    assert item["sentences"][0]["read_boundary_start"]
    assert item["sentences"][0]["read_boundary_end"]
    assert all(not row["context"] for row in item["sentences"])
    assert item["all_sentences_shown"]  # All read snippets shown, not all JD read.


def test_heading_context_can_cross_adjacent_read_chunks_but_not_a_gap():
    text = "方向一：平台建设\n搭建工具。跳过内容。继续维护。"
    split = text.index("搭建")
    adjacent = source(
        build_source_views([evidence(text, end=split), evidence(text, start=split, identity="e2")])
    )
    assert next(row for row in adjacent["sentences"] if "搭建" in row["text"])["context"]
    later = text.index("继续")
    disconnected = source(
        build_source_views([evidence(text, end=split), evidence(text, start=later, identity="e2")])
    )
    assert not disconnected["sentences"][-1]["context"]


def test_job_snapshot_and_list_summary_are_separate_coverage_units():
    rows = [
        evidence("完整正文。"),
        evidence("另一版本。", snapshot="s2", identity="e2"),
        evidence("列表标题", source_layer="summary", identity="e3"),
        evidence("其他岗位。", job="j2", identity="e4"),
    ]
    view = build_source_views(rows)
    assert len(view["jobs"]) == 2 and len(view["jobs"][0]["sources"]) == 3
    summary = source(view, source_index=2)
    assert summary["source_layer"] == "list_summary"
    assert "不是招聘全文" in summary["label"]
    assert not summary["coverage"]["fully_read"]


def test_display_limit_explicit_even_when_whole_body_has_been_read():
    text = "；".join(f"任务{i}" for i in range(205))
    view = build_source_views([evidence(text)])
    item = source(view)
    assert view["sentence_count"] == 200
    assert view["truncated"] and item["truncated"]
    assert not item["all_sentences_shown"] and not view["all_sentences_shown"]
    assert item["coverage"]["fully_read"]


def test_read_evidence_and_text_budgets_are_explicit_not_silent_full_text():
    rows = [evidence("任务。", job=f"j{i}", identity=f"e{i}") for i in range(61)]
    view = build_source_views(rows)
    assert view["accepted_evidence_count"] == 60 and view["truncated"]
    assert not view["all_sentences_shown"]
    assert view["issues"] == [{"code": "evidence_limit", "omitted": 1}]
    large = build_source_views([evidence("字" * 42_001)])
    assert large["jobs"] == [] and large["truncated"]
    assert large["issues"][0]["code"] == "read_text_limit"


@pytest.mark.parametrize("value", [None, {}, "raw text", 2])
def test_unknown_collection_is_not_evidence(value):
    view = build_source_views(value)
    assert not view["jobs"] and not view["all_sentences_shown"]
    assert view["issues"][0]["code"] == "invalid_evidence_collection"


@pytest.mark.parametrize(
    "update",
    [
        {"quote": ""},
        {"start": -1},
        {"end": 999},
        {"start": True},
        {"full_text_length": None},
        {"quote": "与位置不匹配"},
        {"snapshot_id": None},
        {"source_layer": "unknown-report"},
        {"source_layer": {}},
    ],
)
def test_invalid_structures_fail_safely(update):
    row = evidence("任务。") | update
    view = build_source_views([row])
    assert not view["jobs"] and view["issues"]


def test_empty_body_and_conflicting_overlap_or_total_do_not_create_citations():
    empty = build_source_views([evidence("")])
    assert empty["issues"] == [{"index": 0, "code": "empty_body_no_evidence"}]
    for second in [
        evidence("假的。", identity="e2"),
        evidence("任务。", identity="e2") | {"full_text_length": 9},
    ]:
        item = source(build_source_views([evidence("任务。"), second]))
        assert not item["coverage"]["fully_read"]
        assert not item["sentences"] and item["issues"]


@pytest.mark.parametrize(
    "kwargs",
    [{"max_evidence": 61}, {"max_sentences": 201}, {"max_evidence": True}, {"max_sentences": 0}],
)
def test_limits_cannot_be_bypassed(kwargs):
    with pytest.raises(ValueError):
        build_source_views([], **kwargs)
