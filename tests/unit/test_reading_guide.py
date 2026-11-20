"""Ordinary research sees exact cross-chunk qualifiers, never unread text or semantic labels."""

from copy import deepcopy

from work_observer.research.reading import reading_guide


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
