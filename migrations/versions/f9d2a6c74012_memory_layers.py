"""分层记忆作用域、主体、有效期与显式冲突。"""

import sqlalchemy as sa
from alembic import op

revision = "f9d2a6c74012"
down_revision = "e8b1f5c4a086"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "memory_records", sa.Column("scope", sa.String(), nullable=False, server_default="global")
    )
    for name in ("project_id", "subject", "valid_from", "valid_until"):
        op.add_column("memory_records", sa.Column(name, sa.String(), nullable=True))
    op.add_column(
        "memory_records", sa.Column("origin", sa.String(), nullable=False, server_default="user")
    )
    op.add_column(
        "memory_records", sa.Column("conflict_ids", sa.JSON(), nullable=False, server_default="[]")
    )
    op.execute("UPDATE memory_records SET scope='job' WHERE job_id IS NOT NULL")


def downgrade():
    raise RuntimeError("分层记忆包含审核记录，回退请使用迁移前SQLite备份。")
