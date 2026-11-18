"""增量保存有证据和方法版本的岗位工作画像。"""

import sqlalchemy as sa
from alembic import op

revision = "a9d3e6f21042"
down_revision = "f8c2a7d94031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_analyses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("snapshot_id", sa.String(), sa.ForeignKey("job_snapshots.id"), nullable=True),
        sa.Column("cache_key", sa.String(), nullable=False),
        sa.Column("analyzer_version", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("memory_versions", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("cache_key"),
    )
    op.create_index("ix_job_analyses_job_created", "job_analyses", ["job_id", "created_at"])


def downgrade():
    raise RuntimeError("画像保存研究历史；回退请使用迁移前 SQLite 备份。")
