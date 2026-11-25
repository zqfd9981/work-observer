import pytest
from pydantic import ValidationError

from work_observer.research.agent import TOOLS, Answer
from work_observer.research.answering import ReaderAnswer, checked_reader_answer
from work_observer.research.dialogue import tools as dialogue_tools


@pytest.mark.parametrize("mode", ["calibration", "overview", "comparison", "brief"])
def test_reader_layout_chooses_claim_order_without_rewriting_research(mode):
    claims = [{"text": "证据解释"}, {"text": "直接回应用户"}, {"text": "核对用细节"}]
    paragraphs = [
        {"heading": "", "claim_indices": [1]},
        {"heading": "关键依据", "claim_indices": [0]},
    ]
    layout = ReaderAnswer.model_validate({"mode": mode, "paragraphs":
        paragraphs[:1] if mode == "brief" else paragraphs})
    value = checked_reader_answer(layout, claims)
    assert value["paragraphs"][0]["claim_indices"] == [1]
    assert claims[2]["text"] == "核对用细节"
    assert "text" not in value["paragraphs"][0]


@pytest.mark.parametrize("indices", [[3], [-1], [0, 0]])
def test_reader_cannot_reference_nonexistent_or_duplicate_judgments(indices):
    layout = ReaderAnswer.model_validate({"mode": "overview", "paragraphs": [
        {"heading": "", "claim_indices": indices},
    ]})
    with pytest.raises(ValueError):
        checked_reader_answer(layout, [{"text": "唯一的判断"}])


def test_brief_reply_leaves_extra_details_in_research_records():
    layout = ReaderAnswer.model_validate({"mode": "brief", "paragraphs": [
        {"heading": "", "claim_indices": [0, 1]},
    ]})
    with pytest.raises(ValueError, match="一个核心判断"):
        checked_reader_answer(layout, [{"text": "直接答案"}, {"text": "详细理由"}])


def test_reader_indices_are_integers_and_body_cannot_bypass_grounded_claims():
    for paragraph in [{"heading": "", "claim_indices": [True]},
                      {"heading": "", "claim_indices": [0], "text": "无依据的新事实"}]:
        with pytest.raises(ValidationError):
            ReaderAnswer.model_validate({"mode": "brief", "paragraphs": [paragraph]})
    assert checked_reader_answer(None, []) is None


def test_standard_and_followup_finish_tools_expose_strict_reader_layouts():
    for definitions in [TOOLS, dialogue_tools(TOOLS)]:
        schema = next(tool for tool in definitions if tool["name"] == "finish_research")[
            "parameters"
        ]
        assert "reader_answer" in schema["required"]
        assert "default" not in schema["properties"]["reader_answer"]
        assert schema["$defs"]["ReaderParagraph"]["required"] == [
            "purpose", "kind", "heading", "claim_indices", "columns", "rows"]
        assert schema["$defs"]["ReaderParagraph"]["additionalProperties"] is False
    answer = Answer.model_validate({"claims": [{"category": "task", "text": "合成事实",
        "requirement": "unspecified", "evidence_ids": ["E1"]}], "gaps": []})
    assert answer.reader_answer is None


def test_rich_answer_uses_grounded_cells_and_rejects_malformed_tables():
    from work_observer.reports.results import render_reader_answer

    claims = [{"text": "**工作**<script>|内容", "evidence_ids": ["E1"]},
              {"text": "能力依据", "evidence_ids": ["E1"]},
              {"text": "据此推导的建议", "evidence_ids": ["E1"]}]
    table = {"kind": "table", "heading": "任务与能力", "claim_indices": [],
             "columns": ["工作", "能力"], "rows": [[0, 1]]}
    layout = ReaderAnswer.model_validate({"mode": "calibration", "paragraphs": [table,
        {"kind": "numbered", "heading": "准备建议", "claim_indices": [2]}]})
    value = checked_reader_answer(layout, claims)
    markdown = "\n".join(render_reader_answer({"reader_answer": value, "claims": claims,
                                             "evidence": [{"id": "E1"}]}))
    assert "| 工作 | 能力 |" in markdown and "| --- | --- |" in markdown
    assert "**工作**&lt;script&gt;&#124;内容 [E1](#e1)" in markdown
    assert "1. 据此推导的建议" in markdown
    for update in [{"rows": [[0]]}, {"rows": [[0, 4]]}, {"rows": [[0, 0]]},
                   {"columns": ["工作", ""]}, {"claim_indices": [2]}]:
        invalid = ReaderAnswer.model_validate(
            {"mode": "comparison", "paragraphs": [table | update]})
        with pytest.raises(ValueError):
            checked_reader_answer(invalid, claims)


def test_prose_blocks_do_not_silently_drop_table_fields():
    layout = ReaderAnswer.model_validate({"mode": "overview", "paragraphs": [
        {"heading": "", "claim_indices": [0], "rows": [[0, 1]], "columns": ["A", "B"]}]})
    with pytest.raises(ValueError):
        checked_reader_answer(layout, [{"text": "A"}])


def industry_case():
    claims = [{"text": text, "basis": basis, "aggregation": aggregation,
               "evidence_ids": refs} for text, basis, aggregation, refs in [
        ("合成样本支持一个工作结构判断", "synthesis", "common", ["E1", "E2"]),
        ("共性一：系统集成", "synthesis", "common", ["E1", "E2"]),
        ("共性二：效果验证", "synthesis", "common", ["E1", "E2"]),
        ("交付对象", "synthesis", "difference", ["E1", "E2"]),
        ("业务流程", "direct", "none", ["E1"]),
        ("复用平台", "direct", "none", ["E2"]),
        ("保留原看法中成立的部分，补上缺失环节", "inference", "calibration", ["E1", "E2"]),
        ("先选目标方向，用一条可运行流程验证", "inference", "none", ["E1"]),
        ("再用错误案例证明效果定位能力", "inference", "none", ["E2"]),
    ]]
    blocks = [
        {"purpose": "judgment", "kind": "paragraph", "heading": "行业判断", "claim_indices": [0]},
        {"purpose": "common", "kind": "bullets", "heading": "共性", "claim_indices": [1, 2]},
        {"purpose": "difference", "kind": "table", "heading": "分化", "claim_indices": [],
         "columns": ["维度", "应用", "平台"], "rows": [[3, 4, 5]]},
        {"purpose": "calibration", "kind": "paragraph", "heading": "认识校准",
         "claim_indices": [6]},
        {"purpose": "preparation", "kind": "numbered", "heading": "准备影响",
         "claim_indices": [7, 8]},
    ]
    evidence = {"E1": {"job_id": "a"}, "E2": {"job_id": "b"}, "E3": {"job_id": "a"}}
    return {"mode": "industry", "paragraphs": blocks}, claims, evidence


def test_industry_answer_leads_with_synthesis_and_keeps_the_cognitive_flow():
    value, claims, evidence = industry_case()
    checked = checked_reader_answer(ReaderAnswer.model_validate(value), claims, evidence)
    assert [block["purpose"] for block in checked["paragraphs"]] == [
        "judgment", "common", "difference", "calibration", "preparation"]
    value["paragraphs"][1:3] = reversed(value["paragraphs"][1:3])
    with pytest.raises(ValueError, match="先给判断"):
        checked_reader_answer(ReaderAnswer.model_validate(value), claims, evidence)


def test_common_ground_cannot_count_fragments_of_one_job_as_different_jobs():
    value, claims, evidence = industry_case()
    claims[1]["evidence_ids"] = ["E1", "E3"]
    with pytest.raises(ValueError, match="同岗多个片段"):
        checked_reader_answer(ReaderAnswer.model_validate(value), claims, evidence)


def test_industry_differences_are_compared_on_short_dimensions():
    value, claims, evidence = industry_case()
    claims[3]["text"] = "岗位的长职责摘要" * 4
    with pytest.raises(ValueError, match="比较维度"):
        checked_reader_answer(ReaderAnswer.model_validate(value), claims, evidence)


def test_industry_tables_reject_long_jd_paragraphs_instead_of_truncating_them():
    value, claims, evidence = industry_case()
    claims[4]["text"] = "长段JD" * 21
    with pytest.raises(ValueError, match="最多80"):
        checked_reader_answer(ReaderAnswer.model_validate(value), claims, evidence)
    # Existing saved rich answers remain readable with their original content.
    value["mode"] = "comparison"
    assert checked_reader_answer(ReaderAnswer.model_validate(value), claims)
    with pytest.raises(ValueError, match="最多80"):
        checked_reader_answer(ReaderAnswer.model_validate(value), claims, evidence)
