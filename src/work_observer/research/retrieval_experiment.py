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
RECORD_HEADER = "本地检索表达对照 · 本机实际运行记录\n\n"


def record_text(result):
    return RECORD_HEADER + json.dumps(
        {key: value for key, value in result.items() if key != "artifact_text"},
        ensure_ascii=False, separators=(",", ":"),
    )


def read_record(text):
    _, marker, body = text.partition(RECORD_HEADER)
    if not marker:
        raise ValueError("这份材料没有完整的本地检索对照输入，请从检索练习的运行记录继续。")
    try:
        record = json.loads(body)
        record["input"] = RetrievalComparisonInput.model_validate(record["input"]).model_dump()
        if (not isinstance(record.get("sources"), list)
                or not isinstance(record.get("aliases"), dict)
                or not isinstance(record.get("runs"), list)
                or any(not isinstance(row, dict) or not isinstance(row.get("key"), str)
                       for row in record["sources"])):
            raise ValueError("missing source context")
        rows = record.get("comparison_rows")
        if (not isinstance(rows, list) or len(rows) != 2
                or any(not isinstance(row, dict) or any(not isinstance(row.get(key), str)
                                                       for key in ("condition", "observed"))
                       for row in rows)):
            raise ValueError("missing recorded observations")
        return record
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("这份检索记录的输入不完整，原练习仍保留；可另开一次对照。") from exc


def comparison_changes(previous, current):
    changes = []
    for key, label in (("baseline", "原查询"), ("candidate", "改写查询"), ("top_k", "片段上限")):
        if previous["input"][key] != current["input"][key]:
            changes.append(label)
    for fields, label in ((("job_ids", "document_ids"), "对照资料"),
                          (("expected_job_ids", "expected_document_ids"), "预期相关标签")):
        if any(set(previous["input"][key]) != set(current["input"][key]) for key in fields):
            changes.append(label)
    if previous["input"]["expectation"] != current["input"]["expectation"]:
        changes.append("应命中或不应命中的预期")
    if previous["aliases"] != current["aliases"]:
        changes.append("别名配置")

    def versions(record):
        return {row["key"]: (row.get("snapshot_id"), row.get("content_sha256"))
                for row in record["sources"]
                if isinstance(row, dict) and isinstance(row.get("key"), str)}

    before, after = versions(previous), versions(current)
    if before.keys() != after.keys() and "对照资料" not in changes:
        changes.append("原文可读取情况")
    if any(before[key] != after[key] for key in before.keys() & after.keys()):
        changes.append("原文内容")

    def excluded(record):
        return {key for run in record.get("runs", []) if isinstance(run, dict)
                for key in (run.get("excluded_integrity_ids") or []) if isinstance(key, str)}

    if excluded(previous) != excluded(current):
        changes.append("原文完整性排除")
    return changes


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
    result["artifact_text"] = record_text(result)
    return result
