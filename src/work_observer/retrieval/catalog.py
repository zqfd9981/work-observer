"""参数化 SQL 筛选、完整口径统计与有版本的原文片段。"""

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.orm import Session

from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.models import (
    CollectionRun,
    Company,
    Job,
    JobObservation,
    JobSnapshot,
    SourceDocument,
    Watchset,
)


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str | None = None
    company: str | None = None
    keyword: str | None = None
    education: str | None = None
    experience: str | None = None
    salary_min: Decimal | None = Field(default=None, ge=0)
    salary_max: Decimal | None = Field(default=None, ge=0)
    salary_unit: Literal["month", "year", "day", "hour"] = "month"
    detail: Literal["all", "detail", "list_only"] = "all"
    source: Literal["boss", "manual"] | None = None

    @model_validator(mode="after")
    def validate_range(self):
        if self.salary_min is not None and self.salary_max is not None:
            if self.salary_min > self.salary_max:
                raise ValueError("薪资下限不能大于上限")
        return self


def classifications(filters):
    """每个条件有匹配、不匹配、未知三个状态；已知不匹配优先。"""
    matches, unknowns = [], []
    for column, value in (
        (Job.city, filters.city),
        (Job.company_name_raw, filters.company),
        (Job.education_raw, filters.education),
        (Job.experience_raw, filters.experience),
    ):
        if value:
            unknown = or_(column.is_(None), column == "")
            matches.append(and_(not_(unknown), column.contains(value, autoescape=True)))
            unknowns.append(unknown)
    if filters.keyword:
        # 摘要未命中且正文缺失时，全文条件仍未知。
        tags = func.json_each(Job.source_skills).table_valued("value")
        match = or_(
            *[
                func.instr(func.lower(func.coalesce(col, "")), filters.keyword.lower()) > 0
                for col in (Job.title, Job.description_text)
            ],
            select(1)
            .select_from(tags)
            .where(func.instr(func.lower(tags.c.value), filters.keyword.lower()) > 0)
            .exists(),
        )
        unknown = and_(not_(match), Job.description_text.is_(None))
        matches.append(match)
        unknowns.append(unknown)
    if filters.salary_min is not None or filters.salary_max is not None:
        unknown = or_(
            Job.salary_min.is_(None),
            Job.salary_max.is_(None),
            Job.salary_currency.is_(None),
            Job.salary_unit.is_(None),
            Job.salary_currency != "CNY",
            Job.salary_unit != filters.salary_unit,
        )
        bounds = []
        if filters.salary_min is not None:
            bounds.append(Job.salary_max >= filters.salary_min)
        if filters.salary_max is not None:
            bounds.append(Job.salary_min <= filters.salary_max)
        matches.append(and_(not_(unknown), *bounds))
        unknowns.append(unknown)
    if filters.detail != "all":
        matches.append(Job.detail_state == filters.detail)
        unknowns.append(Job.detail_state.is_(None))
    if filters.source:
        matches.append(Job.source == filters.source)
        unknowns.append(Job.source.is_(None))
    if not matches:
        return case((Job.id.is_not(None), "matched"), else_="excluded")
    possible = and_(*[or_(m, u) for m, u in zip(matches, unknowns, strict=True)])
    return case(
        (and_(*matches), "matched"),
        (and_(possible, or_(*unknowns)), "unknown"),
        else_="excluded",
    )


def summary(session, job, match_status="matched"):
    result = {
        "id": job.id,
        "title": job.title,
        "company": job.company_name_raw,
        "company_id": job.company_id,
        "city": job.city,
        "salary": job.salary_raw,
        "salary_unit": job.salary_unit,
        "education": job.education_raw,
        "experience": job.experience_raw,
        "status": job.status,
        "status_observed_at": job.status_observed_at,
        "detail_state": job.detail_state,
        "has_detail": bool(job.description_text),
        "source": job.source,
        "first_observed_at": job.first_observed_at,
        "last_observed_at": job.last_observed_at,
        "detail_collected_at": job.detail_collected_at,
        "source_published_at": job.source_published_at,
        "match_status": match_status,
    }
    company = session.get(Company, job.company_id) if job.company_id else None
    result["company_identity_status"] = company.identity_status if company else "unknown"
    for label, group in (("summary_source", "title"), ("detail_source", "description_text")):
        document_id = (job.field_document_ids or {}).get(group)
        document = session.get(SourceDocument, document_id) if document_id else None
        result[label] = (
            {
                "document_id": document.id,
                "response_origin": document.response_origin,
                "input_kind": document.provenance.get("input_kind"),
                "import_asset_id": document.provenance.get("import_asset_id"),
                "transport": document.transport,
                "observed_at": document.observed_at,
                "archived_at": document.archived_at,
                "source_fetched_at": document.source_fetched_at,
                "data_kind": document.provenance.get("data_kind", "unspecified"),
            }
            if document
            else None
        )
    return result


class Catalog:
    def __init__(self, repository):
        self.repository = repository

    def query(self, filters=None, *, limit=20, offset=0, job_ids=None):
        filters = filters or Filters()
        status = classifications(filters)
        base = select(Job).where(Job.id.in_(job_ids)) if job_ids is not None else select(Job)
        with Session(self.repository.engine) as session:
            scoped = base.add_columns(status.label("match_status")).subquery()
            counts = dict(
                session.execute(
                    select(scoped.c.match_status, func.count()).group_by(scoped.c.match_status)
                ).all()
            )
            candidates = base.where(status != "excluded")
            detail_count = session.scalar(
                select(func.count()).select_from(
                    candidates.where(Job.description_text.is_not(None)).subquery()
                )
            )
            rows = session.execute(
                candidates.add_columns(status)
                .order_by(Job.last_observed_at.desc(), Job.id)
                .offset(offset)
                .limit(limit)
            ).all()
            return {
                "filters": filters.model_dump(mode="json"),
                "counts": {
                    "scope_total": sum(counts.values()),
                    "matched": counts.get("matched", 0),
                    "unknown": counts.get("unknown", 0),
                    "excluded": counts.get("excluded", 0),
                    "candidate_details": detail_count,
                },
                "jobs": [summary(session, job, state) for job, state in rows],
                "offset": offset,
                "limit": limit,
                "truncated": offset + len(rows)
                < sum(counts.get(key, 0) for key in ("matched", "unknown")),
                "rules": "薪资按 CNY 同周期区间相交；学历和经验按原文子串；"
                "未知单列。统计先于分页。",
            }

    def evidence(self, job_id, *, terms=(), limit=4):
        """只取当前正文对应的不可变版本，附真实观察而非版本创建时间。"""
        with Session(self.repository.engine) as session:
            job = session.get(Job, job_id)
            if not job:
                raise ProbeError("JOB_NOT_FOUND")
            document_id = (job.field_document_ids or {}).get("description_text")
            if not job.description_text or not document_id:
                return []
            row = session.execute(
                select(JobObservation, JobSnapshot, SourceDocument, CollectionRun, Watchset)
                .join(JobSnapshot, JobObservation.snapshot_id == JobSnapshot.id)
                .join(SourceDocument, JobObservation.document_id == SourceDocument.id)
                .join(CollectionRun, JobObservation.collection_run_id == CollectionRun.id)
                .join(Watchset, CollectionRun.watchset_id == Watchset.id)
                .where(
                    JobObservation.job_id == job_id,
                    JobObservation.document_id == document_id,
                    JobObservation.kind == "detail",
                )
            ).first()
            if not row:
                raise ProbeError("EVIDENCE_NOT_FOUND")
            observation, snapshot, document, run, watchset = row
            text = snapshot.payload.get("description", "")
            if text != job.description_text:
                raise ProbeError("EVIDENCE_CONTENT_MISMATCH")
            chunks = []
            for start in range(0, len(text), 700):
                quote = text[start : start + 700]
                score = sum(quote.casefold().count(term.casefold()) for term in terms if term)
                if terms and not score:
                    continue
                chunks.append((score, start, quote))
            chunks.sort(key=lambda chunk: (-chunk[0], chunk[1]))
            return [
                {
                    "id": f"{snapshot.id}:{start}:{start + len(quote)}",
                    "job_id": job.id,
                    "title": job.title,
                    "company": job.company_name_raw,
                    "snapshot_id": snapshot.id,
                    "content_sha256": snapshot.content_sha256,
                    "document_id": document.id,
                    "document_sha256": document.sha256,
                    "quote": quote,
                    "start": start,
                    "end": start + len(quote),
                    "full_text_length": len(text),
                    "source": job.source,
                    "data_kind": document.provenance.get("data_kind", "unspecified"),
                    "response_origin": document.response_origin,
                    "input_kind": document.provenance.get("input_kind"),
                    "import_asset_id": document.provenance.get("import_asset_id"),
                    "transport": document.transport,
                    "mode": run.mode,
                    "observed_at": observation.observed_at,
                    "processed_at": observation.processed_at,
                    "source_fetched_at": document.source_fetched_at,
                    "source_published_at": job.source_published_at,
                    "watchset": {"name": watchset.name, "version": watchset.version},
                }
                for _, start, quote in chunks[:limit]
            ]

    def search(self, terms, *, filters=None, job_ids=None, limit=10):
        if not terms or len(terms) > 10 or any(not t.strip() or len(t) > 100 for t in terms):
            raise ProbeError("INVALID_SEARCH_TERMS")
        # SQL 先限定候选和全文命中；不将片段数量当岗位总数。
        status = classifications(filters or Filters())
        hit = or_(*[func.instr(func.lower(Job.description_text), t.lower()) > 0 for t in terms])
        statement = select(Job.id).where(status != "excluded", hit)
        if job_ids is not None:
            statement = statement.where(Job.id.in_(job_ids))
        with Session(self.repository.engine) as session:
            total = session.scalar(select(func.count()).select_from(statement.subquery()))
            identities = session.scalars(statement.order_by(Job.id).limit(limit)).all()
        evidence = [
            item for identity in identities for item in self.evidence(identity, terms=terms)
        ]
        return {"matching_jobs": total, "evidence": evidence[:limit], "limit": limit}

    def document(self, document_id):
        with Session(self.repository.engine) as session:
            document = session.get(SourceDocument, document_id)
            if not document:
                raise ProbeError("DOCUMENT_NOT_FOUND")
            path = Path(document.path)
            intact = (
                path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
            )
            observations = session.scalars(
                select(JobObservation).where(JobObservation.document_id == document_id)
            ).all()
            return {
                "document_id": document.id,
                "path": str(path.resolve()),
                "sha256": document.sha256,
                "integrity": "verified" if intact else "missing_or_changed",
                "response_origin": document.response_origin,
                "input_kind": document.provenance.get("input_kind"),
                "import_asset_id": document.provenance.get("import_asset_id"),
                "transport": document.transport,
                "observed_at": document.observed_at,
                "archived_at": document.archived_at,
                "source_fetched_at": document.source_fetched_at,
                "related_job_id": document.provenance.get("related_job_id"),
                "versions": [
                    {
                        "job_id": observation.job_id,
                        "snapshot_id": observation.snapshot_id,
                        "kind": observation.kind,
                        "payload": session.get(JobSnapshot, observation.snapshot_id).payload,
                    }
                    for observation in observations
                ],
            }
