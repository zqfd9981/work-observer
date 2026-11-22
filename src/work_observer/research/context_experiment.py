"""Inspect two finite context snapshots in memory; no real synchronization is performed."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContextEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=500)


class ContextCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    edge: list[ContextEntry] = Field(max_length=8)
    cloud: list[ContextEntry] = Field(max_length=8)


class ContextCasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cases: list[ContextCase] = Field(min_length=1, max_length=4)
    data_kind: Literal["synthetic", "user_provided"] = "synthetic"

    @model_validator(mode="after")
    def bounded_cases(self):
        if len({row.name for row in self.cases}) != len(self.cases):
            raise ValueError("请为各组输入填写不同名称。")
        if any(not row.edge and not row.cloud for row in self.cases):
            raise ValueError("每组至少填写一条本地或云端记录。")
        if sum(len(row.edge) + len(row.cloud) for row in self.cases) > 32:
            raise ValueError("本次最多比较32条记录。")
        return self


CONDITIONS = (
    "每组独立计算，端侧在前、云侧在后。编号和内容按输入文字比较，不判断语义、新旧或权威。"
    "直接拼接保留每条输入；按编号合并仅折叠同编号同内容的副本，冲突内容全部保留待核对。"
    "缺少一端的记录不能据此解释为删除；没有模拟真实网络、数据库、时序或并发同步。"
)


def run_context_experiment(cases, data_kind="synthetic"):
    inputs = ContextCasesInput.model_validate({"cases": cases, "data_kind": data_kind})
    results, rows = [], []
    for case in inputs.cases:
        appended, grouped = [], {}
        for side in ("edge", "cloud"):
            for position, entry in enumerate(getattr(case, side), 1):
                origin = {"side": side, "position": position}
                appended.append({**entry.model_dump(), **origin})
                variants = grouped.setdefault(entry.key, {})
                variants.setdefault(entry.value, []).append(origin)
        merged = [{
            "key": key,
            "variants": [{"value": value, "origins": origins}
                         for value, origins in variants.items()],
            "sides": list(dict.fromkeys(origin["side"] for origins in variants.values()
                                        for origin in origins)),
            "status": "conflict" if len(variants) > 1 else (
                "both_sides" if len({origin["side"] for origins in variants.values()
                                    for origin in origins}) == 2 else "one_side_only"
            ),
        } for key, variants in grouped.items()]
        folded = len(appended) - sum(len(row["variants"]) for row in merged)
        conflicts = [row["key"] for row in merged if row["status"] == "conflict"]
        one_sided = [row["key"] for row in merged if len(row["sides"]) == 1]
        results.append({"name": case.name, "input": case.model_dump(), "appended": appended,
                        "merged": merged, "folded_copies": folded,
                        "conflicting_keys": conflicts, "one_sided_keys": one_sided})
        rows.append({
            "condition": case.name,
            "input": f"端侧{len(case.edge)}条，云侧{len(case.cloud)}条。",
            "expected": "",
            "observed": (f"直接拼接保留{len(appended)}条；按编号归组{len(merged)}组，"
                         f"折叠同内容副本{folded}条；冲突编号{len(conflicts)}个，"
                         f"仅一端出现的编号{len(one_sided)}个。冲突未自动解决。"),
        })
    outcome = (f"已在本机计算{len(results)}组上下文快照的拼接与按编号合并。"
               "逐条输入、来源和冲突内容保留在运行记录中；结果不能证明真实同步正确、"
               "删除已传播、语义一致或已具备端云工程经验。")
    result = {"conditions": CONDITIONS, "data_kind": inputs.data_kind, "cases": results,
              "comparison_rows": rows, "outcome": outcome}
    result["artifact_text"] = "\n\n".join([
        "本地上下文合并练习 · 本机计算输出", CONDITIONS,
        "输入为构造样例。" if data_kind == "synthetic" else "输入由用户提供，未独立核实来源。",
        json.dumps(results, ensure_ascii=False, indent=2), outcome,
    ])
    return result
