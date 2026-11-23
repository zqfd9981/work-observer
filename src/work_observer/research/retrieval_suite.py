"""A small learner-labelled set of local lexical retrieval comparisons."""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_observer.collection.contracts import now
from work_observer.research.retrieval_experiment import (
    NOTICE,
    RetrievalComparisonInput,
    RetrievalQuery,
    compare_returns,
    comparison_changes,
    record_text,
    run_retrieval_comparison,
)
from work_observer.tracking.evaluation import StrategyService


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    question: str = Field(default="", max_length=1500)
    label_reason: str = Field(default="", max_length=1500)
    baseline: RetrievalQuery
    candidate: RetrievalQuery
    expectation: Literal["sources", "none"] = "sources"
    expected_job_ids: list[str] = Field(default_factory=list, max_length=6)
    expected_document_ids: list[str] = Field(default_factory=list, max_length=6)


class RetrievalSuiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    job_ids: list[str] = Field(default_factory=list, max_length=6)
    document_ids: list[str] = Field(default_factory=list, max_length=6)
    top_k: int = Field(default=3, strict=True, ge=1, le=5)
    cases: list[RetrievalCase] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_cases(self):
        names = [row.name.casefold() for row in self.cases]
        if len(names) != len(set(names)):
            raise ValueError("请给每条评估样例填写不同的名称。")
        for row in self.cases:
            RetrievalComparisonInput.model_validate({
                "job_ids": self.job_ids, "document_ids": self.document_ids, "top_k": self.top_k,
                **row.model_dump(exclude={"name", "question", "label_reason"}),
            })
        return self


def run_retrieval_suite(repository, raw):
    data = RetrievalSuiteInput.model_validate(raw)
    cutoff = now()
    aliases = StrategyService(repository).active_config()["aliases"]
    shared = data.model_dump(exclude={"cases"})
    runs, rows, cases = [], [], []
    sources = []
    for case in data.cases:
        result = run_retrieval_comparison(
            repository, {**shared, **case.model_dump(exclude={"name", "question", "label_reason"})},
            as_of=cutoff, alias_groups=aliases,
        )
        sources = result["sources"]
        cases.append({"name": case.name, "run_indices": [len(runs), len(runs) + 1]})
        for run, row in zip(result["runs"], result["comparison_rows"], strict=True):
            runs.append({**run, "name": case.name + " · " + run["name"]})
            rows.append({**row, "condition": case.name + " · " + row["condition"]})
    selected = {*("job:" + key for key in data.job_ids),
                *("document:" + key for key in data.document_ids)}
    complete = selected <= {row["key"] for row in sources if row["integrity"] == "verified"}
    if not complete:
        for run in runs:
            run["metrics"]["correct_no_match"] = None
    totals = []
    for offset, name in enumerate(("原表达", "改写表达")):
        group = runs[offset::2]
        returned = sum(row["metrics"]["returned_sources"] for row in group)
        expected = sum(row["metrics"]["expected_sources"] for row in group)
        matched = sum(row["metrics"]["matched_expected_sources"] for row in group)
        totals.append({
            "name": name, "case_count": len(group), "returned_case_sources": returned,
            "expected_case_sources": expected, "matched_case_sources": matched,
            "source_precision": matched / returned if returned else None,
            "source_recall": matched / expected if expected else None,
            "exact_label_matches": sum(not row["missing_expected_source_keys"]
                                       and not row["unexpected_source_keys"] for row in group)
            if complete else None,
        })
    result = {
        "record_kind": "retrieval_suite", "input": data.model_dump(), "as_of": cutoff,
        "aliases": aliases, "sources": sources, "cases": cases, "runs": runs,
        "totals": totals, "corpus_complete": complete, "comparison_rows": rows,
        "conditions": f"{len(data.cases)}条使用者样例共用同一批{len(selected)}份原文、"
        f"截止时点{cutoff}、别名配置和top-{data.top_k}片段上限；每条分别保留问题、标签依据和查询。",
        "notice": NOTICE + "累计指标按样例×来源计数，同一来源可在不同样例重复计入；"
        "样例不是随机或独立标注，不能推断全库表现。原文不完整时不计算标签完全一致数。",
        "outcome": f"本机实际运行{len(data.cases)}条样例、{len(runs)}组词面查询；"
        "逐条保存命中、漏回和额外来源，不以累计指标代替失败样例核对。",
    }
    result["artifact_text"] = record_text(result)
    return result


def compare_suites(previous, current):
    """Pair named cases; additions and removals do not receive imaginary prior results."""
    def records(suite):
        shared = {key: suite["input"][key] for key in ("job_ids", "document_ids", "top_k")}
        return {case["name"].casefold(): {
            "name": case["name"], "as_of": suite["as_of"], "sources": suite["sources"],
            "aliases": suite["aliases"],
            "input": {**shared, **{key: value for key, value in case.items() if key != "name"}},
            "runs": suite["runs"][index * 2:index * 2 + 2],
        } for index, case in enumerate(suite["input"]["cases"])}

    def summary(record):
        if record is None:
            return None
        return {"input": record["input"], "runs": [{key: run[key] for key in (
            "name", "query", "metrics", "returned_source_keys", "missing_expected_source_keys",
            "unexpected_source_keys",
        )} for run in record["runs"]]}

    before, after = records(previous), records(current)
    cases = []
    for key in dict.fromkeys([*after, *before]):
        old, new = before.get(key), after.get(key)
        cases.append({
            "name": (new or old)["name"],
            "state": "matched" if old and new else "added" if new else "removed",
            "before": summary(old), "after": summary(new),
            "changed_conditions": comparison_changes(old, new) if old and new else [],
            "return_comparison": compare_returns(old, new) if old and new else [],
        })
    return {
        "kind": "retrieval_suite", "as_of": previous["as_of"],
        "shared_changed_conditions": comparison_changes(previous, current, query_and_labels=False),
        "cases": cases,
        "notice": "按同名样例对照两次实际记录，顺序变化不改变配对；改名视为移除旧样例与新增。"
        "新增、移除样例没有另一侧结果，不能填零或合并为改善率。标签、范围、原文、"
        "别名或片段上限变化都可能影响数字，不能只凭指标变化断言修复、语义效果或岗位能力。",
    }


def select_case(review, name):
    cases = review.get("input", {}).get("cases", [])
    index = next((i for i, row in enumerate(cases)
                  if row["name"].casefold() == name.strip().casefold()), None)
    if index is None or len(review.get("runs", [])) < index * 2 + 2:
        raise ValueError("这份已保存的评估集中没有完整的所选样例，请重新选择。")
    return deepcopy({
        "name": cases[index]["name"], "input": cases[index],
        "runs": review["runs"][index * 2:index * 2 + 2],
        "notice": "这是用户明确选中的一条已运行样例；标签仍是使用者预期。"
        "先读取运行产物，再回查选定原文，限定本次追问，不替换为整组泛论。",
    })
