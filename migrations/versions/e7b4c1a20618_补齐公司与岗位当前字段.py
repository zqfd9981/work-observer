"""增量建立公司和岗位当前信息，保留原有档案及执行记录。"""

import sqlalchemy as sa
from alembic import op

from work_observer.storage.projection import company_v1, origin_v1, project_job_v1

revision = "e7b4c1a20618"
down_revision = "d3cff3ef944a"
branch_labels = None
depends_on = None

TEXT_FIELDS = (
    "company_name_raw title job_url employment_type source_position_code source_position_name "
    "city district address salary_raw salary_currency salary_unit experience_raw education_raw "
    "education_level status_observed_at first_closed_observed_at source_published_at "
    "source_published_raw last_seen_in_search_at detail_collected_at content_updated_at "
    "access_captured_at days_per_week_raw least_month_raw pay_type_raw recruitment_count_raw"
).split()


def upgrade():
    op.create_table(
        "companies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_company_id", sa.String(), nullable=True),
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("identity_status", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("industry_raw", sa.String(), nullable=True),
        sa.Column("scale_raw", sa.String(), nullable=True),
        sa.Column("stage_raw", sa.String(), nullable=True),
        sa.Column("introduction", sa.Text(), nullable=True),
        sa.Column("first_observed_at", sa.String(), nullable=False),
        sa.Column("last_observed_at", sa.String(), nullable=False),
        sa.UniqueConstraint("source", "identity_key"),
        sa.UniqueConstraint("source", "source_company_id"),
    )
    op.create_index("ix_companies_name", "companies", ["name"])
    # SQLite 支持为可空新列内联添加外键，避免重建有历史外键引用的 jobs。
    op.execute("ALTER TABLE jobs ADD COLUMN company_id VARCHAR REFERENCES companies(id)")
    for name in TEXT_FIELDS:
        op.add_column("jobs", sa.Column(name, sa.String(), nullable=True))
    for name in ("raw_job_type", "salary_months"):
        op.add_column("jobs", sa.Column(name, sa.Integer(), nullable=True))
    for name in ("salary_min", "salary_max"):
        op.add_column("jobs", sa.Column(name, sa.Numeric(12, 2), nullable=True))
    for name in ("experience_min_years", "experience_max_years"):
        op.add_column("jobs", sa.Column(name, sa.Numeric(4, 1), nullable=True))
    op.add_column("jobs", sa.Column("description_text", sa.Text(), nullable=True))
    for name in ("source_skills", "welfare_tags", "job_labels", "source_status_raw"):
        op.add_column("jobs", sa.Column(name, sa.JSON(), nullable=True))
    for name in ("access_context", "field_observed_at", "field_document_ids"):
        op.add_column("jobs", sa.Column(name, sa.JSON(), nullable=False, server_default="{}"))
    for name, value in (("status", "unknown"), ("detail_state", "list_only")):
        op.add_column("jobs", sa.Column(name, sa.String(), nullable=False, server_default=value))
    op.create_index("ix_jobs_company_id", "jobs", ["company_id"])
    op.create_index("ix_jobs_city_status", "jobs", ["city", "status"])
    op.create_index("ix_jobs_first_observed_at", "jobs", ["first_observed_at"])
    for name, value in (("source", "boss"), ("transport", "mcp"), ("kind", "collection")):
        op.add_column(
            "collection_runs", sa.Column(name, sa.String(), nullable=False, server_default=value)
        )
    op.add_column(
        "source_documents",
        sa.Column("transport", sa.String(), nullable=False, server_default="mcp"),
    )
    op.add_column(
        "source_documents",
        sa.Column("response_origin", sa.String(), nullable=False, server_default="unknown"),
    )
    op.add_column("source_documents", sa.Column("source_fetched_at", sa.String(), nullable=True))
    op.add_column(
        "job_observations",
        sa.Column("response_origin", sa.String(), nullable=False, server_default="unknown"),
    )
    backfill()


def backfill():
    bind = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(bind=bind)
    jobs, companies = metadata.tables["jobs"], metadata.tables["companies"]
    observations, snapshots = metadata.tables["job_observations"], metadata.tables["job_snapshots"]
    documents = metadata.tables["source_documents"]
    origins = {}
    for doc in bind.execute(sa.select(documents)).mappings():
        origin = origin_v1(doc["provenance"])
        origins[doc["id"]] = origin
        bind.execute(
            documents.update().where(documents.c.id == doc["id"]).values(response_origin=origin)
        )
    current = {r["id"]: dict(r) for r in bind.execute(sa.select(jobs)).mappings()}
    company_rows = {}
    statement = (
        sa.select(observations, snapshots.c.payload)
        .join(snapshots, observations.c.snapshot_id == snapshots.c.id)
        .order_by(observations.c.observed_at, observations.c.processed_at, observations.c.id)
    )
    for row in bind.execute(statement).mappings():
        item = current[row["job_id"]]
        record = {**row["payload"], **(row["access_context"] or {})}
        stamp = row["observed_at"]
        company = company_v1(item["source"], item["source_job_id"], record)
        if company:
            previous = company_rows.get(company["id"])
            if previous:
                previous.update({k: v for k, v in company.items() if v is not None and v != ""})
                previous["last_observed_at"] = stamp
            else:
                company_rows[company["id"]] = {
                    **company,
                    "first_observed_at": stamp,
                    "last_observed_at": stamp,
                }
            item["company_id"] = company["id"]
        item.update(project_job_v1(item, record, row["kind"], stamp, row["document_id"]))
        bind.execute(
            observations.update()
            .where(observations.c.id == row["id"])
            .values(
                response_origin=origins[row["document_id"]],
            )
        )
    if company_rows:
        bind.execute(companies.insert(), list(company_rows.values()))
    for item in current.values():
        bind.execute(
            jobs.update()
            .where(jobs.c.id == item["id"])
            .values(
                **{
                    k: v
                    for k, v in item.items()
                    if k
                    not in {
                        "id",
                        "source",
                        "source_job_id",
                        "first_observed_at",
                        "last_observed_at",
                    }
                }
            )
        )


def downgrade():
    raise RuntimeError(
        "该迁移已回填业务字段；回退请使用迁移前的 SQLite 备份，避免丢失公司与岗位资料。"
    )
