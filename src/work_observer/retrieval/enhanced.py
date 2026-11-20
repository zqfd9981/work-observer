"""有界别名检索、历史来源重建与完整样本的字面统计。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.catalog import Filters
from work_observer.storage.models import (
    CollectionRun,
    Job,
    JobObservation,
    JobSnapshot,
    SourceDocument,
    Watchset,
)
from work_observer.storage.projection import project_job_v1
from work_observer.text_match import match_text

DEFAULT_ALIASES = {
    "Agent": ["智能体"],
    "RAG": ["检索增强", "检索增强生成"],
    "评估": ["评测", "评估集", "评测集"],
    "后端可靠性": ["限流", "重试", "降级", "可观测性"],
    "工具调用": ["function calling", "tool calling"],
    "部署": ["上线", "容器", "Docker"],
}


def normalized_time(value):
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError("timezone required")
        return stamp.astimezone(UTC).isoformat()
    except (ValueError, TypeError) as exc:
        raise ProbeError("INVALID_RETRIEVAL_TIME") from exc


def validated_terms(terms):
    if (
        not isinstance(terms, list)
        or not 1 <= len(terms) <= 10
        or any(not isinstance(term, str) or not term.strip() or len(term) > 100 for term in terms)
    ):
        raise ProbeError("INVALID_SEARCH_TERMS")
    return list(dict.fromkeys(term.strip() for term in terms))


def classify(record, source, filters):
    """与Catalog相同的三值筛选语义，只读取重建字段。"""
    states = []
    for field, needle in (
        ("city", filters.city),
        ("company_name_raw", filters.company),
        ("education_raw", filters.education),
        ("experience_raw", filters.experience),
    ):
        if needle:
            value = record.get(field)
            states.append(
                "unknown"
                if not value
                else "matched"
                if needle.casefold() in value.casefold()
                else "excluded"
            )
    if filters.keyword:
        needle = match_text(filters.keyword)
        values = [record.get("title"), record.get("description_text")]
        values.extend(record.get("source_skills") or [])
        hit = any(needle in match_text(str(value or "")) for value in values)
        states.append(
            "matched" if hit else "unknown" if not record.get("description_text") else "excluded"
        )
    if filters.salary_min is not None or filters.salary_max is not None:
        if (
            record.get("salary_min") is None
            or record.get("salary_max") is None
            or record.get("salary_currency") != "CNY"
            or record.get("salary_unit") != filters.salary_unit
        ):
            states.append("unknown")
        else:
            matches = (
                filters.salary_min is None or record["salary_max"] >= filters.salary_min
            ) and (filters.salary_max is None or record["salary_min"] <= filters.salary_max)
            states.append("matched" if matches else "excluded")
    if filters.detail != "all":
        state = "detail" if record.get("description_text") else "list_only"
        states.append("matched" if state == filters.detail else "excluded")
    if filters.source:
        states.append("matched" if filters.source == source else "excluded")
    return "excluded" if "excluded" in states else "unknown" if "unknown" in states else "matched"


class RetrievalService:
    def __init__(self, repository, alias_groups=None):
        self.repository = repository
        self.alias_groups = alias_groups

    def _expand(self, terms, aliases):
        if not aliases:
            return terms
        groups = self.alias_groups
        if groups is None:
            from work_observer.tracking.evaluation import StrategyService

            groups = StrategyService(self.repository).active_config()["aliases"]
        expanded = list(terms)
        for key, values in groups.items():
            group = [key, *values]
            if {match_text(term) for term in terms} & {match_text(term) for term in group}:
                expanded.extend(group)
        return list(dict.fromkeys(expanded))[:40]

    def _records(self, filters, job_ids, as_of):
        filters = filters if isinstance(filters, Filters) else Filters.model_validate(filters or {})
        cutoff = normalized_time(as_of)
        statement = (
            select(JobObservation, JobSnapshot, SourceDocument, CollectionRun, Watchset, Job.source)
            .join(JobSnapshot, JobObservation.snapshot_id == JobSnapshot.id)
            .join(SourceDocument, JobObservation.document_id == SourceDocument.id)
            .join(CollectionRun, JobObservation.collection_run_id == CollectionRun.id)
            .join(Watchset, CollectionRun.watchset_id == Watchset.id)
            .join(Job, JobObservation.job_id == Job.id)
            .order_by(
                JobObservation.observed_at,
                JobObservation.processed_at,
                JobObservation.id,
            )
        )
        if job_ids is not None:
            if not isinstance(job_ids, list) or len(job_ids) > 5000:
                raise ProbeError("INVALID_RETRIEVAL_SCOPE")
            statement = statement.where(JobObservation.job_id.in_(job_ids))
        if cutoff:
            statement = statement.where(
                JobObservation.observed_at <= cutoff, JobObservation.processed_at <= cutoff
            )
        records, documents = {}, {}
        with Session(self.repository.engine) as session:
            for row in session.execute(statement):
                observation, snapshot, document, run, watchset, source = row
                record = records.setdefault(observation.job_id, {"source": source})
                record.update(
                    project_job_v1(
                        record,
                        snapshot.payload,
                        observation.kind,
                        observation.observed_at,
                        document.id,
                    )
                )
                documents[(observation.job_id, document.id)] = (
                    observation,
                    snapshot,
                    document,
                    run,
                    watchset,
                )
            output = []
            for job_id, record in records.items():
                state = classify(record, record["source"], filters)
                document_id = record.get("field_document_ids", {}).get("description_text")
                output.append(
                    {
                        "job_id": job_id,
                        "record": record,
                        "state": state,
                        "row": documents.get((job_id, document_id)),
                    }
                )
            return output, filters, cutoff

    @staticmethod
    def _sample(records, filters, as_of):
        counts = {key: 0 for key in ("matched", "unknown", "excluded")}
        details = {key: 0 for key in counts}
        for item in records:
            state = item["state"]
            counts[state] += 1
            details[state] += bool(item["record"].get("description_text"))
        return {
            "scope_total": len(records),
            **counts,
            "matched_details": details["matched"],
            "unknown_details": details["unknown"],
            "matched_missing_details": counts["matched"] - details["matched"],
            "denominator": details["matched"],
            "filters": filters.model_dump(mode="json"),
            "as_of": as_of,
            "time_rule": "来源观察与本地入库时间均不晚于截止时间；发布时间未保存于版本时未知。",
            "denominator_rule": "完整范围中明确符合条件且有详情正文的去重岗位；未知条件单列。",
        }

    @staticmethod
    def _evidence(item, start, score, matched_terms, label_hits):
        observation, snapshot, document, run, watchset = item["row"]
        record = item["record"]
        text = snapshot.payload.get("description", "")
        quote = text[start : start + 700]
        return {
            "id": f"{snapshot.id}:{start}:{start + len(quote)}",
            "job_id": item["job_id"],
            "title": snapshot.payload.get("title") or record.get("title"),
            "company": snapshot.payload.get("company") or record.get("company_name_raw"),
            "snapshot_id": snapshot.id,
            "content_sha256": snapshot.content_sha256,
            "document_id": document.id,
            "document_sha256": document.sha256,
            "quote": quote,
            "start": start,
            "end": start + len(quote),
            "full_text_length": len(text),
            "source": record["source"],
            "data_kind": document.provenance.get("data_kind", "unspecified"),
            "response_origin": document.response_origin,
            "transport": document.transport,
            "mode": run.mode,
            "observed_at": observation.observed_at,
            "processed_at": observation.processed_at,
            "source_fetched_at": document.source_fetched_at,
            "source_published_at": None,
            "watchset": {"name": watchset.name, "version": watchset.version},
            "retrieval": {
                "score": score,
                "matched_terms": matched_terms,
                "source_label_hits": label_hits,
                "match_status": item["state"],
                "note": "字面或来源标签命中只用于召回，不代表必备要求；正文引用保持原文。",
            },
        }

    def search(self, terms, filters=None, job_ids=None, as_of=None, limit=10, aliases=True):
        terms = validated_terms(terms)
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 20):
            raise ProbeError("INVALID_RETRIEVAL_LIMIT")
        expanded = self._expand(terms, aliases)
        records, filters, cutoff = self._records(filters, job_ids, as_of)
        ranked, tag_only, matching_jobs = [], [], set()
        for item in records:
            if item["state"] == "excluded":
                continue
            record = item["record"]
            text = record.get("description_text") or ""
            labels = record.get("source_skills") or []
            label_hits = [
                label
                for label in labels
                if any(match_text(term) in match_text(str(label)) for term in expanded)
            ]
            if label_hits and not text:
                tag_only.append(
                    {"job_id": item["job_id"], "labels": label_hits, "state": item["state"]}
                )
            chunks = []
            if text and item["row"]:
                # 百字符重叠覆盖最长检索词跨片段边界的情况，原文位置保持不变。
                for start in range(0, len(text), 600):
                    quote = text[start : start + 700]
                    folded = match_text(quote)
                    matches = [term for term in expanded if match_text(term) in folded]
                    score = sum(folded.count(match_text(term)) for term in matches)
                    if matches or label_hits and start == 0:
                        chunks.append((score + bool(label_hits), start, matches))
            if chunks:
                matching_jobs.add(item["job_id"])
                chunks.sort(key=lambda chunk: (-chunk[0], chunk[1]))
                for index, (score, start, matches) in enumerate(chunks):
                    ranked.append(
                        (
                            index > 0,
                            -score,
                            item["job_id"],
                            start,
                            self._evidence(item, start, score, matches, label_hits),
                        )
                    )
        ranked.sort(key=lambda row: row[:4])
        evidence, seen, characters = [], set(), 0
        for *_, item in ranked:
            if item["id"] in seen or limit is not None and characters + len(item["quote"]) > 7000:
                continue
            seen.add(item["id"])
            evidence.append(item)
            characters += len(item["quote"])
            if limit is not None and len(evidence) >= limit:
                break
        return {
            "terms": terms,
            "expanded_terms": expanded,
            "aliases": aliases,
            "sample": self._sample(records, filters, cutoff),
            "scope_job_ids": [item["job_id"] for item in records if item["state"] != "excluded"],
            "matching_jobs": len(matching_jobs),
            "evidence": evidence,
            "tag_only_hits": tag_only[:20],
            "context_characters": characters,
            "context_limit": 7000 if limit is not None else None,
            "limit": limit,
            "truncated": len(ranked) > len(evidence),
        }

    def stats(self, terms, filters=None, job_ids=None, as_of=None):
        terms = validated_terms(terms)
        records, filters, cutoff = self._records(filters, job_ids, as_of)
        eligible = [
            item
            for item in records
            if item["state"] == "matched" and item["record"].get("description_text")
        ]
        unknown = [
            item
            for item in records
            if item["state"] == "unknown" and item["record"].get("description_text")
        ]
        result = []
        for term in terms:
            hits = [
                item["job_id"]
                for item in eligible
                if match_text(term) in match_text(item["record"]["description_text"])
            ]
            uncertain = sum(
                match_text(term) in match_text(item["record"]["description_text"])
                for item in unknown
            )
            result.append(
                {
                    "term": term,
                    "literal_jobs": len(hits),
                    "denominator": len(eligible),
                    "ratio": len(hits) / len(eligible) if eligible else None,
                    "unknown_scope_literal_jobs": uncertain,
                    "job_ids": hits,
                }
            )
        return {
            "sample": self._sample(records, filters, cutoff),
            "statistics": result,
            "match_mode": "literal",
            "interpretation": (
                "字面出现（统一大小写和同形部首），非必备要求；"
                "不含同义推断，不代表全市场需求占比或时间趋势。"
            ),
            "evidence": [],
        }
