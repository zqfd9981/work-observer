"""Bind saved work types to their original research without changing existing values."""

import sqlalchemy as sa
from alembic import op

revision = "fc15d9fa7145"
down_revision = "fb04c8e96034"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "domain_definitions",
        sa.Column("source_context", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("domain_definitions", "source_context")
