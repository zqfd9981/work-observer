"""检索策略实验及显式启用/回退记录。"""

import sqlalchemy as sa
from alembic import op

revision = "b4e8c2f17053"
down_revision = "a9d3e6f21042"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "retrieval_strategies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "strategy_experiments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "strategy_id", sa.String(), sa.ForeignKey("retrieval_strategies.id"), nullable=False
        ),
        sa.Column("suite_version", sa.String(), nullable=False),
        sa.Column("contract", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_strategy_experiments_strategy_id", "strategy_experiments", ["strategy_id"])
    op.create_table(
        "strategy_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "strategy_id", sa.String(), sa.ForeignKey("retrieval_strategies.id"), nullable=False
        ),
        sa.Column("previous_strategy_id", sa.String(), sa.ForeignKey("retrieval_strategies.id")),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade():
    raise RuntimeError("策略记录包含实验与回退历史，请用迁移前备份回退。")
