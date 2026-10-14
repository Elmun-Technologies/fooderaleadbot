"""Add tracking_links table (named ad links managed from the admin panel).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracking_links",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="other", nullable=False),
        sa.Column(
            "created_by", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tracking_links_payload", "tracking_links", ["payload"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tracking_links_payload", table_name="tracking_links")
    op.drop_table("tracking_links")
