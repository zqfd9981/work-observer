"""Feedback-only regression for observed false rejections; synthetic engine turns."""

import asyncio
import json

import pytest
from test_review_feedback_repair import Model, options
from test_review_feedback_repair import workspace as workspace

from work_observer.config import Settings
from work_observer.research.agent import research
from work_observer.research.requirements import required_markers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("优先条件不能提升为必备。", []),
        ("不能将这些能力归为必备。", []),
        ("不拆出必备部分。", []),
        ("不能把Python归为必备，Java必备。", ["必备"]),
        ("不能只把Python归为必备，Java也必备。", ["必备", "必备"]),
        ("不是优先而是必备。", ["必备"]),
        ("不能提升为优先，Python必备。", ["必备"]),
        ("未明确归为必备；Python实际必备。", ["必备", "必备"]),
    ],
)
def test_feedback_negation_is_local_and_does_not_hide_positive_required(text, expected):
    assert required_markers(text, contextual_negation=True) == expected


class ExplanationModel(Model):
    def __init__(self, text):
        super().__init__()
        self.text = text

    async def turn(self, history):
        outputs, call = await super().turn(history)
        if call["name"] == "finish_research":
            repaired = any(
                json.loads(row["output"]).get("mixed_requirement_claim_indices")
                for row in history
                if row.get("type") == "function_call_output"
            )
            args = json.loads(call["arguments"])
            args["claims"][0]["text"] = "Docker实战经验者优先。" if repaired else self.text
            if repaired and "Python必备" in self.text:
                args["claims"].append(
                    {**args["claims"][0], "requirement": "required", "text": "具备Python开发能力。"}
                )
            call["arguments"] = json.dumps(args)
        return outputs, call


@pytest.mark.parametrize(
    "text",
    [
        "Docker经验优先，不能提升为必备。",
        "Docker经验优先；不能将这些能力归为必备。",
        "Docker经验优先，不拆出必备部分。",
    ],
)
def test_feedback_engine_accepts_negative_strength_explanations_without_retry(workspace, text):
    repo, _, job, _, original, _, _ = workspace
    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            model=ExplanationModel(text),
            **options(job, original),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 3
    assert result["claims"][0]["requirement"] == "preferred"
    assert result["claims"][0]["text"] == text


def test_plain_standard_guard_remains_unchanged(workspace):
    repo, _, job, _, original, _, _ = workspace
    text = "Docker经验优先，不能提升为必备。"
    assert required_markers(text) == ["必备"]
    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            job_ids=[job],
            model=ExplanationModel(text),
            max_calls=4,
            allow_proposals=False,
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 4


def test_feedback_engine_still_splits_a_real_positive_required_clause(workspace):
    repo, _, job, _, original, _, _ = workspace
    result = asyncio.run(
        research(
            repo,
            original["question"],
            Settings(),
            model=ExplanationModel("Docker经验优先，不能提升为必备；Python必备。"),
            **options(job, original),
        )
    )
    assert result["status"] == "completed" and result["model_calls"] == 4
    assert [c["requirement"] for c in result["claims"]] == ["preferred", "required"]
