"""增量建立本地有界执行任务、观察时段和收件箱。"""

import sqlalchemy as sa
from alembic import op

revision = "c5f9d3a28064"
down_revision = "b4e8c2f17053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "work_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("watchset_id", sa.String(), sa.ForeignKey("watchsets.id"), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("collection_run_ids", sa.JSON(), nullable=False),
        sa.Column("result_id", sa.String(), sa.ForeignKey("collection_runs.id"), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_work_tasks_state_created", "work_tasks", ["state", "created_at"])
    op.create_table(
        "observation_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("watchset_id", sa.String(), sa.ForeignKey("watchsets.id"), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("related_id", sa.String(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("read_at", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.String(), nullable=True),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_notifications_state_created", "notifications", ["state", "created_at"])


def downgrade():
    raise RuntimeError("任务与收件箱保存历史；回退请使用迁移前SQLite备份。")
