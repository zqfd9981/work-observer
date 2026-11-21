"""Ordinary research sees exact cross-chunk qualifiers, never unread text or semantic labels."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.research.agent import BATCH_JOB_TOOL, TOOLS
from work_observer.research.reading import job_window, job_windows, reading_guide


def receipts():
    text = (
        "岗位职责\n负责接口开发。\n任职资格\n本科及以上学历；具备商科复合教育背景更佳\n"
        "加分项\n有产品孵化经历。"
    )
    boundary = text.index("复合")
    return text, [
        dict(
            id=f"e{i}",
            citation_key=f"E{i}",
            job_id="job",
            snapshot_id="version",
            quote=text[start:end],
            start=start,
            end=end,
            full_text_length=len(text),
        )
        for i, (start, end) in enumerate(((0, boundary), (boundary, len(text))), 1)
    ]


def test_job_windows_continue_without_changing_original_fragments():
    text = "合成岗位说明。" * 1300 + "末尾限制：业务背景只作为加分项。"
    rows = [
        {
            "id": f"f:{start}",
            "start": start,
            "end": min(start + 700, len(text)),
            "quote": text[start : start + 700],
            "full_text_length": len(text),
        }
        for start in range(0, len(text), 700)
    ]
    before = deepcopy(rows)
    first = job_window(rows)
    assert first["start"] == 0 and first["end"] == 5600
    assert first["has_more"] and first["next_start"] == 5600
    second = job_window(rows, first["next_start"])
    assert second["start"] == first["end"] and second["next_start"] is None
    assert second["end"] == len(text) and "末尾限制" in second["evidence"][-1]["quote"]
    middle = job_window(rows, 5650)
    assert middle["start"] == 5600  # Keep the complete original citation around the position.
    assert middle["evidence"][0]["id"] == rows[8]["id"]
    assert job_window(rows, len(text) + 100)["evidence"] == []
    assert job_window([], 0)["full_text_length"] == 0
    assert rows == before
    for row in [*first["evidence"], *second["evidence"]]:
        assert row["quote"] == text[row["start"] : row["end"]]
    for invalid in (-1, True, "5600"):
        with pytest.raises(ProbeError, match="INVALID_JOB_SOURCE_WINDOW"):
            job_window(rows, invalid)


def test_read_job_contract_exposes_a_valid_nullable_position():
    contract = next(row for row in TOOLS if row["name"] == "read_job")["parameters"]
    Draft202012Validator.check_schema(contract)
    validator = Draft202012Validator(contract)
    assert set(contract["required"]) == set(contract["properties"])
    for start in (None, 0, 5600):
        validator.validate({"job_id": "synthetic-job", "start": start})
    for start in (-1, True, "5600"):
        with pytest.raises(ValidationError):
            validator.validate({"job_id": "synthetic-job", "start": start})


def test_batch_reading_keeps_partial_windows_and_original_source_positions():
    text = "合成工作说明。" * 400 + "末尾限定：商科背景只是加分项。"
    long_rows = [
        {
            "id": f"long:{start}",
            "job_id": "long",
            "start": start,
            "end": min(start + 700, len(text)),
            "quote": text[start : start + 700],
            "full_text_length": len(text),
        }
        for start in range(0, len(text), 700)
    ]
    short_rows = [
        {
            "id": "short:0",
            "job_id": "short",
            "start": 0,
            "end": 7,
            "quote": "负责接口验证。",
            "full_text_length": 7,
        }
    ]
    pool = {"long": long_rows, "short": short_rows}
    before = deepcopy(pool)
    result = job_windows(pool, [{"job_id": "long", "start": 0}, {"job_id": "short", "start": None}])
    assert result["evidence"] == [*long_rows[:2], *short_rows]
    assert result["windows"][0]["has_more"] and result["windows"][0]["next_start"] == 1400
    assert not result["windows"][1]["has_more"]
    continued = job_window(long_rows, result["windows"][0]["next_start"])
    assert "末尾限定" in continued["evidence"][-1]["quote"]
    assert continued["next_start"] is None
    assert pool == before
    Draft202012Validator.check_schema(BATCH_JOB_TOOL["parameters"])
    validator = Draft202012Validator(BATCH_JOB_TOOL["parameters"])
    validator.validate({"reads": [{"job_id": "long", "start": 0}]})
    with pytest.raises(ProbeError, match="RESEARCH_SCOPE_VIOLATION"):
        job_windows(pool, [{"job_id": "outside", "start": 0}])
    for invalid in ([], [{"job_id": "short", "start": 0}] * 7):
        with pytest.raises(ProbeError, match="INVALID_JOB_READ_BATCH"):
            job_windows(pool, invalid)
    with pytest.raises(ProbeError, match="INVALID_JOB_SOURCE_WINDOW"):
        job_windows(pool, [{"job_id": "short", "start": True}])


def test_qualifier_across_citations_keeps_whole_literal_condition_and_section():
    text, rows = receipts()
    before = deepcopy(rows)
    guide = reading_guide(rows, {"e1", "e2"})
    source = guide["sources"][0]
    passage = next(row for row in source["passages"] if "复合教育" in row["text"])
    assert passage["text"] == "具备商科复合教育背景更佳\n"
    assert passage["text"] == text[passage["start"] : passage["end"]]
    assert passage["citation_keys"] == ["E1", "E2"] and passage["complete_read"]
    assert [row["text"].strip() for row in passage["headings"]] == ["任职资格"]
    assert [row["text"].strip() for row in source["headings"]] == ["岗位职责", "任职资格", "加分项"]
    assert not {"requirement", "category", "basis"}.intersection(passage)
    assert rows == before


def test_partial_read_does_not_recover_unread_heading_or_prefix_and_stays_in_touched_source():
    text, rows = receipts()
    other = dict(rows[0], id="unrelated", job_id="other", snapshot_id="other-version")
    source = reading_guide([rows[1], other], {"e2"})["sources"][0]
    assert source["job_id"] == "job" and not source["coverage"]["fully_read"]
    assert source["coverage"]["gaps"] == [{"start": 0, "end": rows[1]["start"]}]
    partial = source["passages"][0]
    assert not partial["complete_read"] and partial["headings"] == []
    assert partial["text"].startswith("复合教育") and "具备商科" not in partial["text"]
    assert partial["text"] == text[partial["start"] : partial["end"]]
    assert reading_guide([dict(id="public", public_document_id="p")], {"public"}) is None
