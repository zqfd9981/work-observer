"""Keep numbered source sections separate without inventing work classifications."""

from copy import deepcopy

from work_observer.research.reading import reading_guide


def source_rows(text, ranges):
    return [
        {
            "id": "e" + str(index),
            "citation_key": "E" + str(index),
            "job_id": "synthetic-job",
            "snapshot_id": "saved-version",
            "start": start,
            "end": end,
            "quote": text[start:end],
            "full_text_length": len(text),
        }
        for index, (start, end) in enumerate(ranges)
    ]


def test_numbered_work_captions_keep_their_own_bullets_and_cross_chunk_qualification():
    text = (
        "岗位职责\r\n1. 内部核对工具\r\n- 对照请求与账本，交付内部差异清单🤔。\r\n"
        "- 向内部团队说明口径，验收权未说明。\r\n"
        "2. 客户原型探索\r\n- 开展客户访谈，交付原型与种子用户反馈。\r\n"
        "- 原型不同于内部核对工具，迁移条件仍未知。\r\n"
        "任职资格\r\n具备商科复合教育背景更佳。\r\n加分项\r\n有产品探索经历。"
    )
    cut = text.index("复合")
    rows = source_rows(text, [(0, cut), (cut, len(text))])
    before = deepcopy(rows)
    guide = reading_guide(rows, {row["id"] for row in rows})
    source = guide["sources"][0]
    sections = {row["heading"]["text"].strip(): row for row in source["sections"]}
    internal = sections["1. 内部核对工具"]
    prototype = sections["2. 客户原型探索"]
    first = "".join(row["text"] for row in internal["fragments"])
    second = "".join(row["text"] for row in prototype["fragments"])
    assert "内部差异清单🤔" in first and "种子用户反馈" not in first
    assert "种子用户反馈" in second and "向内部团队说明口径" not in second
    assert [row["text"].strip() for row in internal["context"]] == ["岗位职责"]
    qualifications = sections["任职资格"]["fragments"]
    assert {row["citation_key"] for row in qualifications} == {"E0", "E1"}
    assert "商科复合教育背景更佳" in "".join(row["text"] for row in qualifications)
    assert source["omitted_sections"] == 0
    for section in source["sections"]:
        for span in [section["heading"], *section["context"], *section["fragments"]]:
            assert span["text"] == text[span["start"] : span["end"]]
            evidence = next(row for row in rows if row["citation_key"] == span["citation_key"])
            assert evidence["start"] <= span["start"] < span["end"] <= evidence["end"]
    assert rows == before


def test_unread_heading_gap_does_not_attach_later_bullets_to_an_earlier_section():
    text = (
        "岗位职责\n1. 内部工具\n- 交付内部清单。\n2. 外部原型\n- 种子用户反馈，仅用于外部探索。\n"
    )
    gap_start, gap_end = text.index("2. 外部原型"), text.index("- 种子用户")
    rows = source_rows(text, [(0, gap_start), (gap_end, len(text))])
    source = reading_guide(rows, {row["id"] for row in rows})["sources"][0]
    assert source["coverage"]["gaps"] == [{"start": gap_start, "end": gap_end}]
    sections = [row for row in source["sections"] if row["heading"]]
    assert len(sections) == 1 and sections[0]["heading"]["text"].strip() == "1. 内部工具"
    assert "种子用户" not in str(sections)
    ungrouped = [row for row in source["sections"] if row["heading"] is None]
    assert len(ungrouped) == 1 and "种子用户反馈" in str(ungrouped[0]["fragments"])


def test_numbered_complete_sentences_remain_body_text_not_work_captions():
    text = "任职资格\n1. 熟悉接口测试，有业务背景优先。\n- 说明个人条件的例子。\n"
    rows = source_rows(text, [(0, len(text))])
    sections = reading_guide(rows, {"e0"})["sources"][0]["sections"]
    assert len(sections) == 1 and sections[0]["heading"]["text"].strip() == "任职资格"
    assert "有业务背景优先" in sections[0]["fragments"][0]["text"]


def test_unheaded_duties_are_retained_without_inferred_section_names():
    text = (
        "合成背景：为客户提供核对服务。\n- 交付差异清单，个人权限未说明。\n任职资格\n熟悉接口开发。"
    )
    rows = source_rows(text, [(0, len(text))])
    sections = reading_guide(rows, {"e0"})["sources"][0]["sections"]
    assert sections[0]["heading"] is None
    assert sections[0]["context"] == []
    assert "交付差异清单" in sections[0]["fragments"][0]["text"]
    assert sections[1]["heading"]["text"].strip() == "任职资格"
