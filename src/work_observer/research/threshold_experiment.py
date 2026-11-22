"""Compare explicit screening rules on one finite, labelled set of work cases."""

import json
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScreeningCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=80)
    score: float = Field(strict=True, ge=0, le=1)
    needs_action: bool = Field(strict=True)


class ThresholdCasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    cases: list[ScreeningCaseInput] = Field(min_length=1, max_length=40)
    thresholds: list[Annotated[float, Field(strict=True, ge=0, le=1)]] = Field(
        min_length=2,
        max_length=6,
    )
    signal: str = Field(min_length=1, max_length=150)
    conditions: str = Field(min_length=1, max_length=1500)
    data_kind: Literal["synthetic", "user_provided"]
    false_positive_cost: float = Field(strict=True, ge=0, le=1_000_000)
    false_negative_cost: float = Field(strict=True, ge=0, le=1_000_000)
    review_cost: float = Field(strict=True, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def distinct_inputs(self):
        if len({row.name for row in self.cases}) != len(self.cases):
            raise ValueError("请为每条案例填写不同名称，以便回查误报与漏报。")
        if len(set(self.thresholds)) != len(self.thresholds):
            raise ValueError("请比较不同阈值。")
        return self


class ThresholdProbeInput(ThresholdCasesInput):
    hypothesis: str = Field(min_length=1, max_length=1500)


NOTICE = (
    "同一批案例中，分数大于等于阈值就进入处理；分数不自动代表概率。"
    "标签是给定的参照，代价是用户指定的单位权重。"
    "这里只计算已给样本，不估计真实业务分布、标签正确性、模型泛化或岗位能力。"
)


def run_threshold_experiment(
    *,
    cases,
    thresholds,
    signal,
    conditions,
    data_kind,
    false_positive_cost,
    false_negative_cost,
    review_cost,
    hypothesis="",
):
    total = len(cases)
    positives = sum(row["needs_action"] for row in cases)
    policies = []

    def ratio(value, denominator):
        return value / denominator if denominator else None

    for threshold in thresholds:
        false_positive, false_negative = [], []
        tp = tn = 0
        for index, row in enumerate(cases):
            selected = Decimal(str(row["score"])) >= Decimal(str(threshold))
            if selected and row["needs_action"]:
                tp += 1
            elif selected:
                false_positive.append(index)
            elif row["needs_action"]:
                false_negative.append(index)
            else:
                tn += 1
        fp, fn = len(false_positive), len(false_negative)
        flagged = tp + fp
        costs = {
            "false_positive": Decimal(str(false_positive_cost)) * fp,
            "false_negative": Decimal(str(false_negative_cost)) * fn,
            "review": Decimal(str(review_cost)) * flagged,
        }
        policies.append(
            {
                "threshold": threshold,
                "true_positive": tp,
                "false_positive": fp,
                "true_negative": tn,
                "false_negative": fn,
                "flagged": flagged,
                "accuracy": ratio(tp + tn, total),
                "precision": ratio(tp, flagged),
                "recall": ratio(tp, positives),
                "flagged_rate": ratio(flagged, total),
                "costs": {key: float(value) for key, value in costs.items()},
                "total_cost": float(sum(costs.values())),
                "false_positive_indices": false_positive,
                "false_negative_indices": false_negative,
            }
        )
    origin = (
        "构造的虚构案例与参照标签"
        if data_kind == "synthetic"
        else "用户提供的案例与参照标签，未独立核实"
    )
    outcome = (
        f"本机对同一批{total}条案例计算{len(thresholds)}个阈值；"
        f"给定标签中{positives}条需要处理。各阈值的正确数、误报、漏报、处理量与指定代价分别保留。"
        "正确率与代价可能指向不同取舍，需结合样本来源与实际工作条件判断。"
    )
    record = {
        "kind": "local_threshold_comparison",
        "signal": signal,
        "conditions": conditions,
        "data_kind": data_kind,
        "data_origin": origin,
        "hypothesis": hypothesis,
        "cases": cases,
        "thresholds": thresholds,
        "false_positive_cost": false_positive_cost,
        "false_negative_cost": false_negative_cost,
        "review_cost": review_cost,
        "total": total,
        "positives": positives,
        "policies": policies,
        "outcome": outcome,
        "notice": NOTICE,
    }
    rows = [
        {
            "condition": f"分数 ≥ {row['threshold']}",
            "input": f"同一批{total}条案例；误报、漏报、处理单价分别为"
            f"{false_positive_cost}、{false_negative_cost}、{review_cost}。",
            "expected": "",
            "observed": f"正确{row['true_positive'] + row['true_negative']}条；"
            f"误报{row['false_positive']}、漏报{row['false_negative']}；"
            f"需处理{row['flagged']}条；给定总代价{row['total_cost']}。",
        }
        for row in policies
    ]
    artifact = "\n\n".join(
        (
            "本地筛选阈值对照 · 本机计算输出",
            origin,
            json.dumps(record, ensure_ascii=False, indent=2),
        )
    )
    return {**record, "comparison_rows": rows, "artifact_text": artifact}
