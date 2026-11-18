"""增量保存用户意图、人工纠正及待审核研究知识；不改已有档案。"""

import sqlalchemy as sa
from alembic import op

revision = "f8c2a7d94031"
down_revision = "e7b4c1a20618"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("root_id", sa.String(), nullable=False),
        sa.Column("previous_id", sa.String(), sa.ForeignKey("memory_records.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("source_run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("root_id", "version"),
    )
    op.create_index("ix_memory_status_kind", "memory_records", ["status", "kind"])
    op.create_index("ix_memory_job", "memory_records", ["job_id"])
    op.create_table(
        "memory_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("memory_id", sa.String(), sa.ForeignKey("memory_records.id"), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_memory_events_memory_id", "memory_events", ["memory_id"])


def downgrade():
    raise RuntimeError("记忆包含用户纠正和历史；回退请使用升级前的 SQLite 备份。")
