"""Compute grouped rates from explicit counts, without inferring business causality."""

import json
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CohortGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    before_total: int = Field(strict=True, ge=0, le=1_000_000_000)
    before_converted: int = Field(strict=True, ge=0, le=1_000_000_000)
    after_total: int = Field(strict=True, ge=0, le=1_000_000_000)
    after_converted: int = Field(strict=True, ge=0, le=1_000_000_000)

    @model_validator(mode="after")
    def valid_counts(self):
        if self.before_converted > self.before_total or self.after_converted > self.after_total:
            raise ValueError("达到指标的数量不能超过该组总数。")
        return self


class CohortCasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    groups: list[CohortGroupInput] = Field(min_length=1, max_length=6)
    metric: str = Field(min_length=1, max_length=150)
    conditions: str = Field(min_length=1, max_length=1500)
    data_kind: Literal["synthetic", "user_provided"]

    @model_validator(mode="after")
    def distinct_groups(self):
        if len({row.name for row in self.groups}) != len(self.groups):
            raise ValueError("请为不同分群填写不同的名称，避免重复计数。")
        return self


class CohortProbeInput(CohortCasesInput):
    hypothesis: str = Field(min_length=1, max_length=1500)


NOTICE = (
    "只按给定计数计算。A、B可能是方案或时间段；可比性依赖相同指标口径与分群定义。"
    "分母为0时不把比率记为0；固定A占比重算B也不是实际干预结果。"
    "这里没有随机分组、统计显著性检验或因果验证，不能证明真实产品改进、岗位能力或业务验收。"
)


def run_cohort_experiment(*, groups, metric, conditions, data_kind):
    """Inputs are validated by CohortCasesInput at the API/tool boundary."""
    totals = {side: sum(row[f"{side}_total"] for row in groups) for side in ("before", "after")}
    converted = {side: sum(row[f"{side}_converted"] for row in groups)
                 for side in ("before", "after")}

    def rate(value, total):
        return Fraction(value, total) if total else None

    def number(value):
        return float(value) if value is not None else None

    def percent(value):
        return f"{float(value) * 100:.6g}%" if value is not None else "无法计算（无样本）"

    observations, changes, weighted_after = [], [], Fraction(0)
    for row in groups:
        before = rate(row["before_converted"], row["before_total"])
        after = rate(row["after_converted"], row["after_total"])
        change = after - before if after is not None and before is not None else None
        changes.append(change)
        weight = rate(row["before_total"], totals["before"])
        if weight and after is None:
            weighted_after = None
        elif weight and weighted_after is not None:
            weighted_after += weight * after
        observations.append({
            **row, "before_rate": number(before), "after_rate": number(after),
            "change": number(change), "before_share": number(weight),
            "after_share": number(rate(row["after_total"], totals["after"])),
        })
    if not totals["before"]:
        weighted_after = None
    before = rate(converted["before"], totals["before"])
    after = rate(converted["after"], totals["after"])
    delta = after - before if after is not None and before is not None else None
    reversal = None if delta is None or any(value is None for value in changes) else (
        delta > 0 and all(value < 0 for value in changes)
        or delta < 0 and all(value > 0 for value in changes)
    )
    overall = {
        "before_total": totals["before"], "before_converted": converted["before"],
        "after_total": totals["after"], "after_converted": converted["after"],
        "before_rate": number(before), "after_rate": number(after), "change": number(delta),
        "after_with_before_mix": number(weighted_after),
        "change_with_before_mix": number(weighted_after - before)
        if weighted_after is not None and before is not None else None,
        "composition_reversal": reversal,
    }
    origin = "构造的虚构数据" if data_kind == "synthetic" else "用户提供的计数，尚未独立核实"
    outcome = (
        f"本机计算{len(groups)}个分群，指标：{metric}。A总体{percent(before)}，"
        f"B总体{percent(after)}；固定A的分群占比重算B为{percent(weighted_after)}。"
        + ("这组输入中，各分群变化方向与总体变化方向相反。" if reversal else "")
        + "这是给定计数下的对照，仍需核对口径、样本来源和实际业务条件。"
    )
    rows = [{
        "condition": row["name"],
        "input": f"A：{row['before_converted']}/{row['before_total']}；"
                 f"B：{row['after_converted']}/{row['after_total']}",
        "expected": "",
        "observed": f"A比率{percent(rate(row['before_converted'], row['before_total']))}，"
                    f"B比率{percent(rate(row['after_converted'], row['after_total']))}。",
    } for row in groups]
    record = {"kind": "local_cohort_comparison", "metric": metric, "conditions": conditions,
              "data_kind": data_kind, "data_origin": origin, "groups": observations,
              "overall": overall, "notice": NOTICE, "outcome": outcome}
    artifact = "\n\n".join(("本地分群指标对照 · 本机计算输出", origin, conditions,
                              json.dumps(record, ensure_ascii=False, indent=2), NOTICE))
    return {**record, "comparison_rows": rows, "artifact_text": artifact}
