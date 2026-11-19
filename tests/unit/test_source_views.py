"""Literal source localization, independent of models, stores or semantic labels."""

import hashlib
from copy import deepcopy

import pytest

from work_observer.research.source_views import build_source_views, model_source_view


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


@pytest.mark.parametrize("colon", ["", "："])
def test_literal_inline_qualification_and_priority_headers_keep_read_context(colon):
    text = (
        f"岗位职责\n负责接口开发。\t 任职要求{colon}\n熟练Python。\n"
        f"优先加分项{colon}\n具有评测经验。"
    )
    item = source(build_source_views([evidence(text)]))
    requirement = next(row for row in item["sentences"] if "熟练Python" in row["text"])
    preferred = next(row for row in item["sentences"] if "具有评测" in row["text"])
    assert [row["text"].strip() for row in requirement["context"]] == [f"任职要求{colon}"]
    assert [row["text"].strip() for row in preferred["context"]] == [
        f"任职要求{colon}",
        f"优先加分项{colon}",
    ]
    for row in [requirement, preferred]:
        assert not {"category", "requirement", "qualification"}.intersection(row)
        for heading in row["context"]:
            assert text[heading["start"] : heading["end"]] == heading["text"]
            assert heading["heuristic"] is True
    assert "".join(row["text"] for row in item["sentences"]) == text


def test_inline_section_recognition_does_not_infer_unread_prefix_or_body_mentions():
    text = "岗位职责\n负责解释任职要求并开发接口。\t 任职要求\n熟练Python。"
    full = source(build_source_views([evidence(text)]))
    mention = next(row for row in full["sentences"] if "负责解释" in row["text"])
    assert not mention["heading_heuristic"]
    start = text.index("\t 任职要求")
    partial = source(build_source_views([evidence(text, start=start)]))
    assert not partial["coverage"]["fully_read"]
    assert all(not row["context"] for row in partial["sentences"])


def test_model_projection_deduplicates_only_provenance_and_does_not_mutate_canonical_view():
    text = "岗位职责：\n负责Python接口开发；任职要求：\n具备调试经验者优先。"
    rows = [
        evidence(text, end=20, document_id="doc", document_sha256="a" * 64),
        evidence(text, start=20, identity="e2"),
    ]
    original = build_source_views(rows)
    before = deepcopy(original)
    compact = model_source_view(original)
    assert original == before
    assert compact["format"] == "source-view-compact-v1"
    for key in ("coverage", "all_sentences_shown", "truncated", "issues"):
        assert source(compact)[key] == source(original)[key]
    actual = {row["id"]: row for row in rows}
    omitted = ("job_id", "snapshot_id", "document_id", "document_sha256", "content_sha256")
    for full, projected in zip(
        source(original)["sentences"], source(compact)["sentences"], strict=True
    ):
        assert all(key not in projected for key in omitted)
        for full_span, small_span in zip(
            (full, *full["context"]), (projected, *projected["context"]), strict=True
        ):
            assert {key: value for key, value in small_span.items() if key != "context"} == {
                key: value for key, value in full_span.items() if key not in (*omitted, "context")
            }
            for key in omitted:
                assert full_span[key] == (actual[small_span["evidence_id"]].get(key) or None)
    # Metadata missing from e2 stays missing; source-level metadata must not fill it.
    assert any(row["document_sha256"] is None for row in source(original)["sentences"])
    projected["context"].clear()
    assert original == before


@pytest.mark.parametrize("cap", [1, 200])
def test_model_projection_preserves_missing_ranges_and_qualifier_unit_flags(cap):
    text = "岗位职责：\n" + "实战经验" * 180 + "者优先。\n负责接口开发。"
    rows = [evidence(text, end=700)]
    full = build_source_views(rows, max_sentences=cap)
    compact = model_source_view(full)
    assert source(compact)["coverage"]["gaps"] == source(full)["coverage"]["gaps"]
    assert not source(compact)["coverage"]["fully_read"]
    assert compact["all_sentences_shown"] == full["all_sentences_shown"]
    for full_row, small_row in zip(
        source(full)["sentences"], source(compact)["sentences"], strict=True
    ):
        for key in (
            "sentence_id",
            "text",
            "start",
            "end",
            "context",
            "unit_complete_read",
            "unit_all_parts_shown",
        ):
            if key != "context":
                assert full_row[key] == small_row[key]
    if cap == 200:
        assert not source(compact)["sentences"][-1]["unit_complete_read"]


def test_model_projection_does_not_recover_citations_from_conflicting_source_metadata():
    text = "建设平台。审核结果。"
    full = build_source_views(
        [
            evidence(text, end=5, document_sha256="a" * 64),
            evidence(text, start=5, identity="e2", document_sha256="b" * 64),
        ]
    )
    compact = model_source_view(full)
    assert source(compact)["sentences"] == []
    assert source(compact)["issues"] == ["conflicting_document_sha256"]
    assert compact["all_sentences_shown"] is False


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


def test_qualification_crossing_700_chunks_is_one_complete_literal_unit_with_all_parts():
    heading = "任职要求：\r\n"
    text = heading + "有" + "Ａ" * (700 - len(heading) - 2) + "者优先；\r\n"
    metadata = {"document_id": "d1", "document_sha256": "a" * 64, "content_sha256": "b" * 64}
    rows = [
        evidence(text, end=700, **metadata),
        evidence(text, start=700, identity="e2", **metadata),
    ]
    item = source(build_source_views(rows))
    parts = item["sentences"][1:]
    assert len(parts) == 2 and parts[0]["text"].endswith("者")
    assert parts[1]["text"] == "优先；\r\n"
    assert len({part["unit_id"] for part in parts}) == 1
    assert all(part["unit_complete_read"] and part["unit_all_parts_shown"] for part in parts)
    assert all(
        part["unit_start"] == len(heading) and part["unit_end"] == len(text) for part in parts
    )
    assert "".join(part["text"] for part in parts) == text[len(heading) :]
    for part in parts:
        assert (
            part["sentence_id"]
            == hashlib.sha256(
                f"{part['evidence_id']}:{part['start']}:{part['end']}".encode()
            ).hexdigest()[:24]
        )  # Original sentence identity contract remains unchanged.
        assert part["context"][0]["text"] == heading
        assert part["context"][0]["start"] == 0 and part["context"][0]["end"] == len(heading)
        assert part["job_id"] == "j1" and part["snapshot_id"] == "s1"
        for key, value in metadata.items():
            assert item[key] == part[key] == part["context"][0][key] == value
    unsplit = source(build_source_views([evidence(text, identity="whole", **metadata)]))
    assert unsplit["sentences"][1]["unit_id"] == parts[0]["unit_id"]
    different = source(build_source_views([evidence(text, job="j2", **metadata)]))
    assert different["sentences"][1]["unit_id"] != parts[0]["unit_id"]
    different = source(build_source_views([evidence(text, snapshot="s2", **metadata)]))
    assert different["sentences"][1]["unit_id"] != parts[0]["unit_id"]


def test_units_at_unknown_window_edges_and_across_gap_are_incomplete_without_invented_bounds():
    text = "前文。熟悉工具者优先；尾文。"
    left, right = text.index("熟悉"), text.index("；") + 1
    whole = source(build_source_views([evidence(text)]))
    qualified = next(row for row in whole["sentences"] if "熟悉" in row["text"])
    assert qualified["unit_complete_read"]
    window = source(build_source_views([evidence(text, start=left, end=right)]))
    assert not window["coverage"]["fully_read"]
    assert window["sentences"][0]["unit_complete_read"] is False  # Left delimiter was not read.
    assert window["sentences"][0]["unit_all_parts_shown"]
    disconnected = source(
        build_source_views(
            [evidence(text, end=left + 2), evidence(text, start=left + 3, identity="e2")]
        )
    )
    pieces = [
        row for row in disconnected["sentences"] if row["start"] >= left and row["start"] < right
    ]
    assert len(pieces) == 2 and len({row["unit_id"] for row in pieces}) == 2
    assert all(not row["unit_complete_read"] for row in pieces)
    assert all(row["unit_all_parts_shown"] for row in pieces)
    assert pieces[0]["unit_end"] < pieces[1]["unit_start"]


def test_display_cut_inside_shared_unit_does_not_masquerade_as_complete_visible_unit():
    prefix = "短句。" * 199
    text = prefix + "具有全角Ａ经验者优先。"
    boundary = len(prefix) + 8
    item = source(
        build_source_views(
            [evidence(text, end=boundary), evidence(text, start=boundary, identity="e2")]
        )
    )
    assert item["coverage"]["fully_read"]
    assert item["truncated"] and not item["all_sentences_shown"]
    part = item["sentences"][-1]
    assert part["unit_complete_read"] and not part["unit_all_parts_shown"]
    assert part["end"] < part["unit_end"] == len(text)
    assert part["unit_start"] == len(prefix)
    assert all(row["unit_all_parts_shown"] for row in item["sentences"][:-1])


@pytest.mark.parametrize("key", ["document_id", "document_sha256", "content_sha256"])
def test_conflicting_source_identity_cannot_silently_share_snapshot(key):
    text = "任职要求：\n工具开发经验者优先。"
    rows = [evidence(text, **{key: "a"}), evidence(text, identity="e2", **{key: "b"})]
    item = source(build_source_views(rows))
    assert item["issues"] == ["conflicting_" + key]
    assert not item["sentences"] and not item["coverage"]["fully_read"]
    assert not item["all_sentences_shown"]


def test_missing_hashes_are_none_and_are_not_borrowed_from_another_piece():
    text = "任职要求：\n具备经验者优先。"
    boundary = text.index("具备")
    item = source(
        build_source_views(
            [
                evidence(text, end=boundary, document_id="d1", document_sha256="a" * 64),
                evidence(text, start=boundary, identity="e2"),
            ]
        )
    )
    assert item["document_id"] == "d1" and item["content_sha256"] is None
    part = item["sentences"][-1]
    assert part["document_id"] is None and part["document_sha256"] is None
    assert part["context"][0]["document_id"] == "d1"
    assert part["unit_complete_read"]
    malformed = build_source_views([evidence(text, document_sha256={"untrusted": "hash"})])
    assert malformed["issues"][0]["code"] == "invalid_source_metadata"
    assert not malformed["jobs"]
