"""人工疑似重复审核与截图精确区域，不改变任何来源记录。"""

import sqlalchemy as sa
from alembic import op

revision = "fb04c8e96034"
down_revision = "fae3b7d85023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "duplicate_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("pair_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.String(), sa.ForeignKey("duplicate_reviews.id")),
        sa.Column("left_job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("right_job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("basis", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("pair_key", "version"),
    )
    op.create_index("ix_duplicate_pair", "duplicate_reviews", ["pair_key"])
    op.create_table(
        "screenshot_regions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("asset_id", sa.String(), sa.ForeignKey("import_assets.id"), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("snapshot_id", sa.String(), sa.ForeignKey("job_snapshots.id"), nullable=False),
        sa.Column("document_id", sa.String(), sa.ForeignKey("source_documents.id"), nullable=False),
        sa.Column("image_sha256", sa.String(), nullable=False),
        sa.Column("document_sha256", sa.String(), nullable=False),
        sa.Column("content_sha256", sa.String(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("selection_method", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("signature", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("signature"),
    )
    op.create_index("ix_region_job", "screenshot_regions", ["job_id"])


def downgrade():
    raise RuntimeError("审核与截图引用保留；回退请使用迁移前SQLite备份。")
