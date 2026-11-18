"""公开网页原始归档与正文索引，不改招聘来源记录。"""

import sqlalchemy as sa
from alembic import op

revision = "d6a0e4b39075"
down_revision = "c5f9d3a28064"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "public_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("final_url", sa.String(), nullable=False),
        sa.Column("publisher", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("text_sha256", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.String(), nullable=False),
        sa.Column("source_published_at", sa.String(), nullable=True),
        sa.Column("extractor_version", sa.String(), nullable=False),
    )
    op.create_index("ix_public_documents_url_time", "public_documents", ["url", "observed_at"])


def downgrade():
    raise RuntimeError("公开原文是研究依据；回退请使用迁移前的SQLite备份。")
