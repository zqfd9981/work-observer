"""静态岗位档案：七类业务表，以及兼容保留的 task_runs 执行记录。"""

from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Watchset(Base):
    __tablename__ = "watchsets"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        UniqueConstraint("name", "config_sha256"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    version: Mapped[int]
    config_sha256: Mapped[str]
    config: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str]


class TaskRun(Base):
    __tablename__ = "task_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[str]
    finished_at: Mapped[str | None]


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), primary_key=True)
    watchset_id: Mapped[str] = mapped_column(ForeignKey("watchsets.id"))
    mode: Mapped[str]
    status: Mapped[str]
    started_at: Mapped[str]
    finished_at: Mapped[str | None]
    coverage: Mapped[dict] = mapped_column(JSON)
    stats: Mapped[dict] = mapped_column(JSON)
    issues: Mapped[list] = mapped_column(JSON)
    stop_reason: Mapped[str | None]
    source: Mapped[str] = mapped_column(default="boss", server_default="boss")
    transport: Mapped[str] = mapped_column(default="mcp", server_default="mcp")
    kind: Mapped[str] = mapped_column(default="collection", server_default="collection")


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("source", "identity_key"),
        UniqueConstraint("source", "source_company_id"),
        Index("ix_companies_name", "name"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str]
    source_company_id: Mapped[str | None]
    identity_key: Mapped[str]
    identity_status: Mapped[str]
    name: Mapped[str]
    industry_raw: Mapped[str | None]
    scale_raw: Mapped[str | None]
    stage_raw: Mapped[str | None]
    introduction: Mapped[str | None] = mapped_column(Text)
    first_observed_at: Mapped[str]
    last_observed_at: Mapped[str]


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id"),
        Index("ix_jobs_company_id", "company_id"),
        Index("ix_jobs_city_status", "city", "status"),
        Index("ix_jobs_first_observed_at", "first_observed_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str]
    source_job_id: Mapped[str]
    first_observed_at: Mapped[str]
    last_observed_at: Mapped[str]
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"))
    company_name_raw: Mapped[str | None]
    title: Mapped[str | None]
    job_url: Mapped[str | None]
    employment_type: Mapped[str | None]
    raw_job_type: Mapped[int | None]
    days_per_week_raw: Mapped[str | None]
    least_month_raw: Mapped[str | None]
    pay_type_raw: Mapped[str | None]
    recruitment_count_raw: Mapped[str | None]
    source_position_code: Mapped[str | None]
    source_position_name: Mapped[str | None]
    city: Mapped[str | None]
    district: Mapped[str | None]
    address: Mapped[str | None]
    salary_raw: Mapped[str | None]
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None]
    salary_unit: Mapped[str | None]
    salary_months: Mapped[int | None]
    experience_raw: Mapped[str | None]
    experience_min_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    experience_max_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    education_raw: Mapped[str | None]
    education_level: Mapped[str | None]
    description_text: Mapped[str | None] = mapped_column(Text)
    source_skills: Mapped[list | None] = mapped_column(JSON)
    welfare_tags: Mapped[list | None] = mapped_column(JSON)
    job_labels: Mapped[list | None] = mapped_column(JSON)
    detail_state: Mapped[str] = mapped_column(default="list_only", server_default="list_only")
    status: Mapped[str] = mapped_column(default="unknown", server_default="unknown")
    source_status_raw: Mapped[dict | None] = mapped_column(JSON)
    status_observed_at: Mapped[str | None]
    first_closed_observed_at: Mapped[str | None]
    source_published_at: Mapped[str | None]
    source_published_raw: Mapped[str | None]
    last_seen_in_search_at: Mapped[str | None]
    detail_collected_at: Mapped[str | None]
    content_updated_at: Mapped[str | None]
    access_context: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    access_captured_at: Mapped[str | None]
    field_observed_at: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    field_document_ids: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class SourceDocument(Base):
    __tablename__ = "source_documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    collection_run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    kind: Mapped[str]
    page: Mapped[int | None]
    source_job_id: Mapped[str | None]
    request: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    path: Mapped[str]
    sha256: Mapped[str]
    observed_at: Mapped[str]
    archived_at: Mapped[str]
    transport: Mapped[str] = mapped_column(default="mcp", server_default="mcp")
    response_origin: Mapped[str] = mapped_column(default="unknown", server_default="unknown")
    source_fetched_at: Mapped[str | None]


class JobSnapshot(Base):
    """岗位内容版本，沿用原表名与外键，列表和详情的原始内容分别留存。"""

    __tablename__ = "job_snapshots"
    __table_args__ = (UniqueConstraint("job_id", "kind", "content_version", "content_sha256"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    kind: Mapped[str]
    content_version: Mapped[str]
    content_sha256: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    first_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    created_at: Mapped[str]


class JobObservation(Base):
    __tablename__ = "job_observations"
    __table_args__ = (
        UniqueConstraint("collection_run_id", "job_id", "kind", "page"),
        Index("ix_observations_job_time", "job_id", "observed_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    collection_run_id: Mapped[str] = mapped_column(ForeignKey("collection_runs.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("job_snapshots.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    kind: Mapped[str]
    page: Mapped[int] = mapped_column(Integer)
    position: Mapped[int | None]
    access_context: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[str]
    processed_at: Mapped[str]
    response_origin: Mapped[str] = mapped_column(default="unknown", server_default="unknown")


class MemoryRecord(Base):
    """用户意图、人工纠正和有来源的派生知识；原始事实仍归来源档案。"""

    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint("root_id", "version"),
        Index("ix_memory_status_kind", "status", "kind"),
        Index("ix_memory_job", "job_id"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    root_id: Mapped[str]
    previous_id: Mapped[str | None] = mapped_column(ForeignKey("memory_records.id"))
    version: Mapped[int]
    kind: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str]
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    evidence: Mapped[list] = mapped_column(JSON)
    source_run_id: Mapped[str | None]
    created_at: Mapped[str]
    updated_at: Mapped[str]
    scope: Mapped[str] = mapped_column(default="global", server_default="global")
    project_id: Mapped[str | None]
    subject: Mapped[str | None]
    valid_from: Mapped[str | None]
    valid_until: Mapped[str | None]
    origin: Mapped[str] = mapped_column(default="user", server_default="user")
    conflict_ids: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")


class MemoryEvent(Base):
    __tablename__ = "memory_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("memory_records.id"), index=True)
    action: Mapped[str]
    created_at: Mapped[str]


class JobAnalysis(Base):
    """带版本的岗位画像派生结果；不是招聘来源事实。"""

    __tablename__ = "job_analyses"
    __table_args__ = (
        UniqueConstraint("cache_key"),
        Index("ix_job_analyses_job_created", "job_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("job_snapshots.id"))
    cache_key: Mapped[str]
    analyzer_version: Mapped[str]
    prompt_version: Mapped[str]
    model_name: Mapped[str]
    memory_versions: Mapped[list] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str]
    created_at: Mapped[str]


# 注册检索策略模型；只新增表，不更改来源档案。
from work_observer.connectors import import_models as _import_models  # noqa: E402, F401
from work_observer.connectors import public_models as _public_models  # noqa: E402, F401
from work_observer.storage import operations_models as _operations_models  # noqa: E402, F401
from work_observer.tracking import models as _tracking_models  # noqa: E402, F401
