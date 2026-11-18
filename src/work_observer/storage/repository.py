"""岗位、快照、观察记录的业务事务；不等待外部请求。"""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from work_observer.collection.contracts import CONTENT_VERSION, access, content, digest, now
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.storage.database import engine_for, require_schema
from work_observer.storage.models import (
    CollectionRun,
    Company,
    Job,
    JobObservation,
    JobSnapshot,
    SourceDocument,
    TaskRun,
    Watchset,
)
from work_observer.storage.projection import company_v1, origin_v1, project_job_v1

TABLES = [
    Company,
    Watchset,
    TaskRun,
    CollectionRun,
    Job,
    JobSnapshot,
    JobObservation,
    SourceDocument,
]


def uid():
    return uuid4().hex


class Repository:
    def __init__(self, path: Path):
        self.engine = engine_for(path)
        try:
            require_schema(self.engine)
        except Exception:
            self.engine.dispose()
            raise

    def close(self):
        self.engine.dispose()

    def begin_run(self, name, spec, mode, *, kind="collection", transport="mcp"):
        if mode not in {"live", "replay", "manual"}:
            raise ProbeError("INVALID_COLLECTION_MODE")
        config = spec.model_dump()
        fingerprint = digest(config)
        stamp = now()
        run_id = uid()
        with Session(self.engine) as session, session.begin():
            modes = set(session.scalars(select(CollectionRun.mode).distinct())) - {"manual"}
            if mode != "manual" and modes - {mode}:
                raise ProbeError("LIVE_AND_REPLAY_DATABASES_MUST_BE_SEPARATE")
            watchset = session.scalar(
                select(Watchset).where(
                    Watchset.name == name,
                    Watchset.config_sha256 == fingerprint,
                )
            )
            if watchset is None:
                version = (
                    session.scalar(
                        select(func.max(Watchset.version)).where(
                            Watchset.name == name,
                        )
                    )
                    or 0
                )
                watchset = Watchset(
                    id=uid(),
                    name=name,
                    version=version + 1,
                    config_sha256=fingerprint,
                    config=config,
                    created_at=stamp,
                )
                session.add(watchset)
                session.flush()
            session.add(TaskRun(id=run_id, kind=kind, status="running", started_at=stamp))
            session.flush()
            session.add(
                CollectionRun(
                    id=run_id,
                    watchset_id=watchset.id,
                    mode=mode,
                    status="running",
                    started_at=stamp,
                    coverage={
                        "pages": [],
                        "details": [],
                        "list_limited": False,
                        "details_limited": False,
                    },
                    stats={
                        "jobs_new": 0,
                        "snapshots_new": 0,
                        "list_records_received": 0,
                        "list_observations": 0,
                        "details_received": 0,
                        "requests_attempted": 0,
                        "remote_tool_calls": 0,
                        "pages_succeeded": 0,
                    },
                    issues=[],
                    source=spec.source,
                    kind=kind,
                    transport=transport,
                )
            )
        return run_id

    def start_step(self, run_id, stage, page, source_job_id=None):
        step_id = uid()
        with Session(self.engine) as session, session.begin():
            run = session.get(CollectionRun, run_id)
            coverage = deepcopy(run.coverage)
            coverage[stage].append(
                {
                    "id": step_id,
                    "page": page,
                    "status": "running",
                    "count": None,
                    "source_job_id": source_job_id,
                }
            )
            run.coverage = coverage
            run.stats = {
                **run.stats,
                "requests_attempted": run.stats["requests_attempted"] + 1,
                "remote_tool_calls": run.stats["remote_tool_calls"]
                + (run.mode == "live" and run.transport == "mcp"),
                **(
                    {"http_request_attempts": run.stats.get("http_request_attempts", 0) + 1}
                    if run.transport == "http" and run.mode == "live"
                    else {}
                ),
            }
        return step_id

    def document(self, run_id, kind, capture, path, sha, page=None, source_job_id=None):
        document_id = uid()
        with Session(self.engine) as session, session.begin():
            session.add(
                SourceDocument(
                    id=document_id,
                    collection_run_id=run_id,
                    kind=kind,
                    page=page,
                    source_job_id=source_job_id,
                    request=capture.request,
                    path=path,
                    sha256=sha,
                    provenance=capture.provenance,
                    observed_at=capture.observed_at,
                    archived_at=now(),
                    transport=capture.provenance.get("transport", "mcp"),
                    response_origin=origin_v1(capture.provenance),
                    source_fetched_at=capture.provenance.get("source_fetched_at"),
                )
            )
        return document_id

    def _observe(self, session, run_id, source, job, kind, page, position, document_id, stamp):
        candidate_id = uid()
        added = session.execute(
            insert(Job)
            .values(
                id=candidate_id,
                source=source,
                source_job_id=job["job_id"],
                first_observed_at=stamp,
                last_observed_at=stamp,
            )
            .on_conflict_do_nothing(index_elements=["source", "source_job_id"])
        ).rowcount
        stored = session.scalar(
            select(Job).where(
                Job.source == source,
                Job.source_job_id == job["job_id"],
            )
        )
        stored.first_observed_at = min(stored.first_observed_at, stamp)
        stored.last_observed_at = max(stored.last_observed_at, stamp)
        prior = session.scalar(
            select(JobObservation.id).where(
                JobObservation.collection_run_id == run_id,
                JobObservation.job_id == stored.id,
                JobObservation.kind == kind,
                JobObservation.page == page,
            )
        )
        if prior:
            return 0, 0, 0
        self._project_current(session, stored, job, kind, stamp, document_id)
        normalized = content(job)
        sha = digest(normalized)
        snapshot_added = session.execute(
            insert(JobSnapshot)
            .values(
                id=uid(),
                job_id=stored.id,
                kind=kind,
                content_version=CONTENT_VERSION,
                content_sha256=sha,
                payload=normalized,
                first_document_id=document_id,
                created_at=now(),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "job_id",
                    "kind",
                    "content_version",
                    "content_sha256",
                ]
            )
        ).rowcount
        snapshot_id = session.scalar(
            select(JobSnapshot.id).where(
                JobSnapshot.job_id == stored.id,
                JobSnapshot.kind == kind,
                JobSnapshot.content_version == CONTENT_VERSION,
                JobSnapshot.content_sha256 == sha,
            )
        )
        session.add(
            JobObservation(
                id=uid(),
                collection_run_id=run_id,
                job_id=stored.id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                kind=kind,
                page=page,
                position=position,
                access_context=access(job),
                observed_at=stamp,
                processed_at=now(),
                response_origin=session.get(SourceDocument, document_id).response_origin,
            )
        )
        session.flush()
        return added, snapshot_added, 1

    @staticmethod
    def _project_current(session, stored, record, kind, stamp, document_id):
        current = {column.name: getattr(stored, column.name) for column in Job.__table__.columns}
        changes = project_job_v1(current, record, kind, stamp, document_id)
        if "company_name_raw" in changes:
            company_values = company_v1(stored.source, stored.source_job_id, record)
            previous = session.get(Company, stored.company_id) if stored.company_id else None
            if (
                previous
                and previous.source_company_id
                and not record.get("source_company_id")
                and record.get("company") == previous.name
            ):
                company_values.update(
                    id=previous.id,
                    source_company_id=previous.source_company_id,
                    identity_key=previous.identity_key,
                    identity_status=previous.identity_status,
                )
            company = session.scalar(
                select(Company).where(
                    Company.source == stored.source,
                    Company.identity_key == company_values["identity_key"],
                )
            )
            if company is None and previous and previous.identity_status == "unverified":
                # 升级临时公司关联，保留其内部编号和已有资料，不按名称合并。
                company = previous
                company_values["id"] = previous.id
            if company is None:
                company = Company(**company_values, first_observed_at=stamp, last_observed_at=stamp)
                session.add(company)
            else:
                company.first_observed_at = min(company.first_observed_at, stamp)
                if stamp >= company.last_observed_at:
                    for key, value in company_values.items():
                        if value is not None and value != "":
                            setattr(company, key, value)
                    company.last_observed_at = stamp
            session.flush()
            stored.company_id = company.id
        for key, value in changes.items():
            setattr(stored, key, value)

    @staticmethod
    def _step(run, stage, step_id, **changes):
        coverage = deepcopy(run.coverage)
        step = next(s for s in coverage[stage] if s["id"] == step_id)
        step.update(changes)
        run.coverage = coverage

    def page(self, run_id, source, page, jobs, pagination, document_id, stamp, step_id):
        with Session(self.engine) as session, session.begin():
            run = session.get(CollectionRun, run_id)
            stats = run.stats.copy()
            for position, job in enumerate(jobs, 1):
                added, snapshots, observations = self._observe(
                    session,
                    run_id,
                    source,
                    job,
                    "list",
                    page,
                    position,
                    document_id,
                    stamp,
                )
                stats["jobs_new"] += added
                stats["snapshots_new"] += snapshots
                stats["list_observations"] += observations
            stats["list_records_received"] += len(jobs)
            stats["pages_succeeded"] += 1
            run.stats = stats
            self._step(
                run,
                "pages",
                step_id,
                status="success",
                count=len(jobs),
                document_id=document_id,
                pagination=pagination,
            )

    def detail(self, run_id, source, page, job, document_id, stamp, step_id):
        with Session(self.engine) as session, session.begin():
            run = session.get(CollectionRun, run_id)
            added, snapshots, observations = self._observe(
                session,
                run_id,
                source,
                job,
                "detail",
                page,
                None,
                document_id,
                stamp,
            )
            run.stats = {
                **run.stats,
                "jobs_new": run.stats["jobs_new"] + added,
                "snapshots_new": run.stats["snapshots_new"] + snapshots,
                "details_received": run.stats["details_received"] + observations,
            }
            self._step(run, "details", step_id, status="success", count=1, document_id=document_id)

    def issue(self, run_id, code, stage, step_id=None, document_id=None):
        with Session(self.engine) as session, session.begin():
            run = session.get(CollectionRun, run_id)
            run.issues = [
                *run.issues,
                {"code": code, "stage": stage, "step_id": step_id, "document_id": document_id},
            ]
            if step_id:
                self._step(
                    run,
                    stage,
                    step_id,
                    status="failed",
                    count=None,
                    error_code=code,
                    document_id=document_id,
                )

    def finish(self, run_id, status, stop_reason, list_limited, details_limited):
        with Session(self.engine) as session, session.begin():
            run = session.get(CollectionRun, run_id)
            run.status = status
            run.stop_reason = stop_reason
            run.finished_at = now()
            run.coverage = {
                **run.coverage,
                "list_limited": list_limited,
                "details_limited": details_limited,
            }
            task = session.get(TaskRun, run_id)
            task.status = status
            task.finished_at = run.finished_at
        return self.run(run_id)

    def run(self, run_id):
        with Session(self.engine) as session:
            run = session.get(CollectionRun, run_id)
            if not run:
                raise ProbeError("RUN_NOT_FOUND")
            watchset = session.get(Watchset, run.watchset_id)
            return {
                "id": run.id,
                "mode": run.mode,
                "status": run.status,
                "watchset": watchset.name,
                "watchset_version": watchset.version,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "stats": run.stats,
                "coverage": run.coverage,
                "issues": run.issues,
                "stop_reason": run.stop_reason,
            }

    def runs(self, limit=10):
        with Session(self.engine) as session:
            ids = session.scalars(
                select(CollectionRun.id)
                .order_by(
                    CollectionRun.started_at.desc(),
                )
                .limit(limit)
            ).all()
        return [self.run(run_id) for run_id in ids]

    def counts(self):
        with Session(self.engine) as session:
            return {
                model.__tablename__: session.scalar(select(func.count()).select_from(model))
                for model in TABLES
            }

    def _job(self, session, job):
        result = {
            "id": job.id,
            "source": job.source,
            "first_observed_at": job.first_observed_at,
            "last_observed_at": job.last_observed_at,
        }
        private = {"source_job_id", "access_context", "access_captured_at", "field_observed_at"}
        result["current"] = {
            col.name: str(value) if isinstance(value, Decimal) else value
            for col in Job.__table__.columns
            if col.name not in private
            for value in [getattr(job, col.name)]
        }
        company = session.get(Company, job.company_id) if job.company_id else None
        result["company_profile"] = self._company(company) if company else None
        result["manual_supplements"] = [
            {"job_id": identity, "title": title}
            for identity, title in session.execute(
                select(Job.id, Job.title)
                .join(JobObservation, JobObservation.job_id == Job.id)
                .join(SourceDocument, JobObservation.document_id == SourceDocument.id)
                .where(
                    Job.source == "manual",
                    SourceDocument.provenance["related_job_id"].as_string() == job.id,
                )
                .distinct()
            )
        ]
        result["provenance"] = {}
        for group, document_id in (job.field_document_ids or {}).items():
            document = session.get(SourceDocument, document_id)
            if document:
                result["provenance"][group] = {
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
        for kind in ("list", "detail"):
            row = session.execute(
                select(JobSnapshot.payload, JobObservation.document_id)
                .join(
                    JobObservation,
                    JobObservation.snapshot_id == JobSnapshot.id,
                )
                .where(JobObservation.job_id == job.id, JobObservation.kind == kind)
                .order_by(
                    JobObservation.observed_at.desc(),
                    JobObservation.processed_at.desc(),
                )
                .limit(1)
            ).first()
            result[kind] = row[0] if row else None
            result[f"{kind}_document_id"] = row[1] if row else None
        return result

    @staticmethod
    def _company(company):
        return {
            key: getattr(company, key)
            for key in (
                "id",
                "name",
                "industry_raw",
                "scale_raw",
                "stage_raw",
                "introduction",
                "identity_status",
                "first_observed_at",
                "last_observed_at",
            )
        }

    def companies(self, limit=20, name=None):
        with Session(self.engine) as session:
            return [
                self._company(company)
                for company in session.scalars(
                    select(Company)
                    .where(Company.name.contains(name, autoescape=True) if name else True)
                    .order_by(Company.last_observed_at.desc(), Company.id)
                    .limit(limit)
                )
            ]

    def company(self, company_id):
        with Session(self.engine) as session:
            company = session.get(Company, company_id)
            if not company:
                raise ProbeError("COMPANY_NOT_FOUND")
            result = self._company(company)
            result["jobs"] = [
                {"id": job.id, "title": job.title, "detail_state": job.detail_state}
                for job in session.scalars(select(Job).where(Job.company_id == company_id))
            ]
            return result

    def jobs(self, limit=20):
        with Session(self.engine) as session:
            return [
                self._job(session, job)
                for job in session.scalars(
                    select(Job)
                    .order_by(
                        Job.last_observed_at.desc(),
                        Job.id,
                    )
                    .limit(limit)
                )
            ]

    def job(self, job_id):
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if not job:
                raise ProbeError("JOB_NOT_FOUND")
            return self._job(session, job)

    def history(self, job_id, limit=20):
        with Session(self.engine) as session:
            if session.get(Job, job_id) is None:
                raise ProbeError("JOB_NOT_FOUND")
            rows = session.execute(
                select(JobObservation, JobSnapshot, SourceDocument)
                .join(JobSnapshot, JobObservation.snapshot_id == JobSnapshot.id)
                .join(SourceDocument, JobObservation.document_id == SourceDocument.id)
                .where(JobObservation.job_id == job_id)
                .order_by(JobObservation.observed_at.desc(), JobObservation.processed_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "observation_id": observation.id,
                    "run_id": observation.collection_run_id,
                    "kind": observation.kind,
                    "page": observation.page,
                    "observed_at": observation.observed_at,
                    "processed_at": observation.processed_at,
                    "snapshot_id": snapshot.id,
                    "content_sha256": snapshot.content_sha256,
                    "payload": snapshot.payload,
                    "document_id": document.id,
                    "document_path": document.path,
                    "document_sha256": document.sha256,
                    "data_kind": document.provenance.get("data_kind", "unspecified"),
                    "response_origin": document.response_origin,
                    "input_kind": document.provenance.get("input_kind"),
                    "import_asset_id": document.provenance.get("import_asset_id"),
                    "transport": document.transport,
                    "source_fetched_at": document.source_fetched_at,
                }
                for observation, snapshot, document in rows
            ]
