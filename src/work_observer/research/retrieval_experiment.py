"""Run two lexical queries against a learner-selected local corpus and source labels."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.public_models import PublicDocument
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.tracking.evaluation import StrategyService

Term = Annotated[str, Field(min_length=1, max_length=100)]


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    terms: list[Term] = Field(min_length=1, max_length=5)
    required_terms: list[Term] = Field(default_factory=list, max_length=3)


class RetrievalComparisonInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    baseline: RetrievalQuery
    candidate: RetrievalQuery
    job_ids: list[str] = Field(default_factory=list, max_length=6)
    document_ids: list[str] = Field(default_factory=list, max_length=6)
    expected_job_ids: list[str] = Field(default_factory=list, max_length=6)
    expected_document_ids: list[str] = Field(default_factory=list, max_length=6)
    expectation: Literal["sources", "none"] = "sources"
    top_k: int = Field(default=3, ge=1, le=5, strict=True)

    @model_validator(mode="after")
    def scope_and_labels(self):
        for field in ("job_ids", "document_ids", "expected_job_ids", "expected_document_ids"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise ValueError("对照资料与预期标签请勿重复选择。")
        if not 1 <= len(self.job_ids) + len(self.document_ids) <= 6:
            raise ValueError("本次小样本对照请选择1至6份原文。")
        if (set(self.expected_job_ids) - set(self.job_ids)
                or set(self.expected_document_ids) - set(self.document_ids)):
            raise ValueError("预期相关资料必须包含在本次对照范围中。")
        labelled = bool(self.expected_job_ids or self.expected_document_ids)
        if (self.expectation == "sources") != labelled:
            raise ValueError("请选择应找到的资料，或明确选择本次不应有相关资料。")
        return self


NOTICE = (
    "这是两组词面查询在本次勾选原文上的本机实际检索；未调用生成模型、向量或外部重排服务。"
    "相关标签是使用者本次的预期，并非独立标注结论。指标按返回片段中的去重来源计算，"
    "不是答案准确率、全库评测或岗位需求占比；标签不完整时不能解释为整体质量。"
    "未返回可能是未命中、top-k限制、正文缺失或完整性排除，不能直接判定资料不相关。"
)


def source_key(item):
    return ("job:" + item["job_id"] if item.get("job_id")
            else "document:" + item["public_document_id"])


def run_retrieval_comparison(repository, raw):
    data = RetrievalComparisonInput.model_validate(raw)
    cutoff = now()
    aliases = StrategyService(repository).active_config()["aliases"]
    retrieval = UnifiedRetrieval(repository, alias_groups=aliases)
    records, _, _ = RetrievalService(repository)._records(None, data.job_ids, cutoff)
    sources = []
    for item in records:
        snapshot = item["row"][1] if item["row"] else None
        sources.append({"key": "job:" + item["job_id"], "title": item["record"].get("title"),
                        "snapshot_id": snapshot.id if snapshot else None,
                        "content_sha256": snapshot.content_sha256 if snapshot else None,
                        "full_text_length": len(item["record"].get("description_text") or "")})
    with Session(repository.engine) as session:
        sources.extend({"key": "document:" + row.id, "title": row.title,
                        "content_sha256": row.text_sha256, "document_sha256": row.sha256,
                        "full_text_length": len(row.text)} for row in session.scalars(
                            select(PublicDocument).where(PublicDocument.id.in_(data.document_ids)),
                        ))
    expected = {*("job:" + key for key in data.expected_job_ids),
                *("document:" + key for key in data.expected_document_ids)}
    runs, rows = [], []
    for name, query in (("原表达", data.baseline), ("改写表达", data.candidate)):
        found = retrieval.search(
            query.terms, required_terms=query.required_terms, job_ids=data.job_ids,
            public_document_ids=data.document_ids, as_of=cutoff, limit=data.top_k,
            include_knowledge=False,
        )
        evidence = [{key: item.get(key) for key in (
            "id", "job_id", "public_document_id", "document_id", "snapshot_id", "title",
            "quote", "start", "end", "content_sha256", "document_sha256", "evidence_kind",
            "source", "observed_at", "data_kind", "retrieval",
        )} for item in found["evidence"]]
        returned = list(dict.fromkeys(source_key(item) for item in evidence))
        matched = sorted(expected & set(returned))
        metrics = {
            "returned_sources": len(returned), "matched_expected_sources": len(matched),
            "expected_sources": len(expected),
            "source_precision": len(matched) / len(returned) if returned else None,
            "source_recall": len(matched) / len(expected) if expected else None,
            "correct_no_match": not returned if data.expectation == "none" else None,
        }
        runs.append({
            "name": name, "query": query.model_dump(), "expanded_terms": found["expanded_terms"],
            "metrics": metrics, "returned_source_keys": returned,
            "missing_expected_source_keys": sorted(expected - set(returned)),
            "unexpected_source_keys": sorted(set(returned) - expected),
            "excluded_integrity_ids": found["excluded_integrity_ids"], "evidence": evidence,
        })
        rows.append({
            "condition": name, "input": " / ".join(query.terms),
            "expected": "不应返回资料" if data.expectation == "none"
            else f"应找回{len(expected)}份已标记资料；见完整标签和原文定位。",
            "observed": f"返回{len(evidence)}段、{len(returned)}份来源；"
            f"命中预期{len(matched)}份，漏回{len(expected - set(returned))}份，"
            f"额外返回{len(set(returned) - expected)}份。",
        })
    conditions = (
        f"两组查询固定同一批{len(data.job_ids) + len(data.document_ids)}份资料、"
        f"同一读取截止时点{cutoff}、同一别名配置和top-{data.top_k}片段上限。"
        "只改变查询表达及须包含的主题；排序分数不能作为相关概率。"
    )
    outcome = "已实际完成两组本地词面检索；命中、漏回和额外返回见条件对照。需逐条核对标签与原文。"
    result = {"input": data.model_dump(), "as_of": cutoff, "aliases": aliases, "sources": sources,
              "runs": runs, "conditions": conditions, "notice": NOTICE,
              "outcome": outcome, "comparison_rows": rows}
    result["artifact_text"] = "本地检索表达对照 · 本机实际运行记录\n\n" + json.dumps(
        result, ensure_ascii=False, separators=(",", ":"),
    )
    return result
