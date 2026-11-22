from copy import deepcopy

import pytest
from pydantic import ValidationError

from work_observer.research.threshold_experiment import (
    ThresholdCasesInput,
    run_threshold_experiment,
)

INPUT = {
    "cases": [
        {"name": "应处理工单", "score": 0.55, "needs_action": True},
        *[
            {"name": f"普通工单{i}", "score": score, "needs_action": False}
            for i, score in enumerate(
                [0.6, 0.52, 0.4, 0.35, 0.25, 0.2, 0.15, 0.1, 0.05, 0.03, 0.01]
            )
        ],
    ],
    "thresholds": [0.5, 0.7],
    "signal": "需要进一步处理的工单",
    "conditions": "构造案例，参照标签和分数固定；仅改变筛选阈值。",
    "data_kind": "synthetic",
    "false_positive_cost": 1,
    "false_negative_cost": 20,
    "review_cost": 0,
}


def test_accuracy_and_supplied_cost_can_prefer_different_rules_without_mutating_inputs():
    before = deepcopy(INPUT)
    result = run_threshold_experiment(**ThresholdCasesInput.model_validate(INPUT).model_dump())
    low, high = result["policies"]
    assert (
        low["true_positive"],
        low["false_positive"],
        low["true_negative"],
        low["false_negative"],
        low["flagged"],
        low["total_cost"],
    ) == (1, 2, 9, 0, 3, 2)
    assert (high["accuracy"], high["recall"], high["precision"], high["total_cost"]) == (
        11 / 12,
        0,
        None,
        20,
    )
    assert high["accuracy"] > low["accuracy"] and high["total_cost"] > low["total_cost"]
    assert high["false_negative_indices"] == [0]
    assert low["false_positive_indices"] == [1, 2]
    changed = run_threshold_experiment(**{**INPUT, "false_negative_cost": 0.1, "review_cost": 2})
    assert changed["policies"][0]["total_cost"] == 8
    assert changed["policies"][1]["total_cost"] == 0.1
    assert INPUT == before


def test_threshold_equality_zero_denominators_and_decimal_costs_remain_explicit():
    result = run_threshold_experiment(
        **{
            **INPUT,
            "cases": [{"name": "边界负例", "score": 0.5, "needs_action": False}],
            "false_positive_cost": 0.1,
            "review_cost": 0.2,
        }
    )
    low, high = result["policies"]
    assert low["false_positive"] == 1 and low["total_cost"] == 0.3
    assert low["recall"] is None and low["precision"] == 0
    assert high["recall"] is None and high["precision"] is None
    assert "边界负例" in result["artifact_text"] and result["data_kind"] == "synthetic"
    assert all(not row["expected"] for row in result["comparison_rows"])


@pytest.mark.parametrize(
    "changes",
    [
        {"thresholds": [True, 0.7]},
        {"thresholds": [0.5, float("nan")]},
        {"thresholds": [0.5, 0.5]},
        {"thresholds": [-0.1, 0.5]},
        {"false_positive_cost": -1},
        {"review_cost": float("inf")},
        {"cases": [{"name": "bad", "score": 2, "needs_action": True}]},
        {"cases": [{"name": "bad", "score": 0.5, "needs_action": "false"}]},
    ],
)
def test_invalid_work_inputs_are_not_silently_reinterpreted(changes):
    with pytest.raises(ValidationError):
        ThresholdCasesInput.model_validate({**INPUT, **changes})


def test_full_bounded_input_fits_the_existing_artifact_field_without_truncation():
    values = ThresholdCasesInput.model_validate(
        {
            **INPUT,
            "cases": [
                {"name": str(i) + "🙂" * 77, "score": i / 40, "needs_action": i % 2 == 0}
                for i in range(40)
            ],
            "thresholds": [0, 0.2, 0.4, 0.6, 0.8, 1],
            "conditions": "完整条件" * 375,
        }
    ).model_dump()
    result = run_threshold_experiment(**values, hypothesis="原先预期" * 375)
    assert len(result["artifact_text"]) <= 20_000
    assert values["cases"][-1]["name"] in result["artifact_text"]
