"""A bounded, sequential learning experiment; no network or arbitrary code execution."""

import json

from pydantic import BaseModel, ConfigDict, Field


class RetryRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=1, max_length=60)
    business_id: str = Field(min_length=1, max_length=60)
    action: str = Field(min_length=1, max_length=60)


class RetryCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=150)
    requests: list[RetryRequestInput] = Field(min_length=1, max_length=20)


class RetryCasesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cases: list[RetryCaseInput] = Field(min_length=1, max_length=6)


class RetryProbeInput(RetryCasesInput):
    hypothesis: str = Field(min_length=1, max_length=1500)


RULES = (
    ("none", "不去重"),
    ("request", "按请求编号"),
    ("business", "只按业务编号"),
    ("business_action", "按业务编号和动作"),
)
CONDITIONS = (
    "在本机内存中，按给定顺序逐条处理；每个条件和规则从空记录开始。"
    "动作只作为输入字符串比较，不判断真实业务含义。"
    "这里没有网络、真实数据库或并发执行，也不模拟故障恢复。"
)


def run_retry_experiment(cases):
    if sum(len(case["requests"]) for case in cases) > 20:
        raise ValueError("本地样例最多使用20条请求，请精简后再运行。")
    observations = []
    for case in cases:
        runs = []
        for rule, label in RULES:
            seen, accepted, skipped = set(), [], []
            for index, request in enumerate(case["requests"], 1):
                key = {
                    "none": None,
                    "request": request["request_id"],
                    "business": request["business_id"],
                    "business_action": (request["business_id"], request["action"]),
                }[rule]
                if rule != "none" and key in seen:
                    skipped.append(index)
                else:
                    seen.add(key)
                    accepted.append(index)
            runs.append({"rule": rule, "label": label,
                         "accepted": accepted, "skipped": skipped})
        observations.append({"name": case["name"], "requests": case["requests"], "runs": runs})
    rows = [{
        "condition": case["name"],
        "input": f"本组共{len(case['requests'])}条输入；完整编号、动作和顺序见运行记录。",
        "expected": "",
        "observed": "；".join(
            f"{run['label']}：执行{run['accepted']}，跳过{run['skipped']}"
            for run in case["runs"]
        ),
    } for case in observations]
    outcome = (
        f"已在本机顺序计算{len(cases)}组输入、4种规则。"
        "执行与跳过的位置见条件对照。结果描述这些规则在所给输入上的行为，"
        "不能据此确认真实业务键、并发安全、网络故障恢复或岗位胜任。"
    )
    artifact = "\n\n".join((
        "本地重试与去重学习实验 · 本机计算输出",
        CONDITIONS,
        "输入中的业务编号和动作来自使用者或预置样例，不是从JD验证的真实业务协议。",
        "每组的输入位置从1开始。执行表示向本次内存记录追加一项；跳过表示规则拦下了该位置。",
        json.dumps(observations, ensure_ascii=False, indent=2),
        outcome,
        "下一步应结合实际业务确认哪些操作可以合并；真实并发与恢复行为需另做实验。",
    ))
    return {"conditions": CONDITIONS, "cases": observations, "comparison_rows": rows,
            "outcome": outcome, "artifact_text": artifact}
