"""A small learner-labelled set of local lexical retrieval comparisons."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from work_observer.collection.contracts import now
from work_observer.research.retrieval_experiment import (
    NOTICE,
    RetrievalComparisonInput,
    RetrievalQuery,
    record_text,
    run_retrieval_comparison,
)
from work_observer.tracking.evaluation import StrategyService


class RetrievalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
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
                **row.model_dump(exclude={"name"}),
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
            repository, {**shared, **case.model_dump(exclude={"name"})},
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
        f"截止时点{cutoff}、别名配置和top-{data.top_k}片段上限；每条分别保留查询与标签。",
        "notice": NOTICE + "累计指标按样例×来源计数，同一来源可在不同样例重复计入；"
        "样例不是随机或独立标注，不能推断全库表现。原文不完整时不计算标签完全一致数。",
        "outcome": f"本机实际运行{len(data.cases)}条样例、{len(runs)}组词面查询；"
        "逐条保存命中、漏回和额外来源，不以累计指标代替失败样例核对。",
    }
    result["artifact_text"] = record_text(result)
    return result
