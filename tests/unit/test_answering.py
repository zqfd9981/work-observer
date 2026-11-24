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
        assert schema["$defs"]["ReaderParagraph"]["required"] == ["heading", "claim_indices"]
        assert schema["$defs"]["ReaderParagraph"]["additionalProperties"] is False
    answer = Answer.model_validate({"claims": [{"category": "task", "text": "合成事实",
        "requirement": "unspecified", "evidence_ids": ["E1"]}], "gaps": []})
    assert answer.reader_answer is None
