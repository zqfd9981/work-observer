"""截图原图索引，保留既有招聘与研究行值。"""

import sqlalchemy as sa
from alembic import op

revision = "e8b1f5c4a086"
down_revision = "d6a0e4b39075"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "import_assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("data_kind", sa.String(), nullable=False),
        sa.Column("extraction_status", sa.String(), nullable=False),
        sa.Column("extractor_model", sa.String(), nullable=True),
    )


def downgrade():
    raise RuntimeError("原图是人工核对依据；回退请使用迁移前SQLite备份。")
