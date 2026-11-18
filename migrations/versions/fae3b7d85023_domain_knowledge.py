"""审核领域定义版本与有证据范围的工作关系。"""

import sqlalchemy as sa
from alembic import op

revision = "fae3b7d85023"
down_revision = "f9d2a6c74012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "domain_definitions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("domain_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.String(), sa.ForeignKey("domain_definitions.id")),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("inclusion", sa.Text(), nullable=False),
        sa.Column("exclusion", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("change_kind", sa.String(), nullable=False),
        sa.Column("related_ids", sa.JSON(), nullable=False),
        sa.Column("review_reason", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.String()),
        sa.UniqueConstraint("domain_key", "version"),
    )
    op.create_index("ix_domain_status", "domain_definitions", ["status", "domain_key"])
    op.create_table(
        "work_relations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("domain_id", sa.String(), sa.ForeignKey("domain_definitions.id"), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_text", sa.String(), nullable=False),
        sa.Column("target_kind", sa.String(), nullable=False),
        sa.Column("target_text", sa.String(), nullable=False),
        sa.Column("predicate", sa.String(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("counterevidence", sa.JSON(), nullable=False),
        sa.Column("conflict_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("review_reason", sa.Text()),
        sa.Column("source_run_id", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.String()),
    )
    op.create_index("ix_work_relation_domain_status", "work_relations", ["domain_id", "status"])


def downgrade():
    raise RuntimeError("保留审核及知识版本；回退请使用迁移前备份。")
