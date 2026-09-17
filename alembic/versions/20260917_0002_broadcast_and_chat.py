"""Add broadcasts and chat_messages tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("photo_file_id", sa.String(length=255), nullable=True),
        sa.Column("photo_url", sa.String(length=512), nullable=True),
        sa.Column("document_file_id", sa.String(length=255), nullable=True),
        sa.Column("document_url", sa.String(length=512), nullable=True),
        sa.Column("document_name", sa.String(length=255), nullable=True),
        sa.Column("filter_classification", sa.String(length=32), nullable=True),
        sa.Column("filter_status", sa.String(length=32), nullable=True),
        sa.Column("filter_source", sa.String(length=32), nullable=True),
        sa.Column("filter_campaign", sa.String(length=128), nullable=True),
        sa.Column("filter_lead_type", sa.String(length=16), nullable=True),
        sa.Column("filter_language", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_by_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("created_by_username", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "lead_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column(
            "telegram_user_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(length=16), server_default="inbound", nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("photo_file_id", sa.String(length=255), nullable=True),
        sa.Column("document_file_id", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_type", sa.String(length=32), nullable=True),
        sa.Column(
            "admin_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("admin_username", sa.String(length=64), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.create_index(
            "ix_chat_messages_lead_created", ["lead_id", "created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_chat_messages_lead_id"), ["lead_id"], unique=False)
        batch_op.create_index(
            "ix_chat_messages_user_created", ["telegram_user_id", "created_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_chat_messages_telegram_user_id"), ["telegram_user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_chat_messages_created_at"), ["created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_chat_messages_created_at"))
        batch_op.drop_index(batch_op.f("ix_chat_messages_telegram_user_id"))
        batch_op.drop_index("ix_chat_messages_user_created")
        batch_op.drop_index(batch_op.f("ix_chat_messages_lead_id"))
        batch_op.drop_index("ix_chat_messages_lead_created")

    op.drop_table("chat_messages")
    op.drop_table("broadcasts")
