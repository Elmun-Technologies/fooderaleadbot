"""Add follow-up marketing tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "followup_templates",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("delay_hours", sa.Integer(), server_default="1", nullable=False),
        sa.Column("language", sa.String(length=8), server_default="uz", nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("photo_file_id", sa.String(length=255), nullable=True),
        sa.Column("document_file_id", sa.String(length=255), nullable=True),
        sa.Column("document_name", sa.String(length=255), nullable=True),
        sa.Column("filter_classification", sa.String(length=32), nullable=True),
        sa.Column("filter_lead_type", sa.String(length=16), nullable=True),
        sa.Column("filter_source", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_sent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("followup_templates", schema=None) as batch_op:
        batch_op.create_index(
            "ix_followup_templates_trigger_active", ["trigger", "is_active"], unique=False
        )
        batch_op.create_index(
            "ix_followup_templates_lang_active", ["language", "is_active"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_followup_templates_trigger"), ["trigger"], unique=False)

    op.create_table(
        "followup_logs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "template_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("lead_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column(
            "telegram_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("bot_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bot_user_id"], ["bot_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["followup_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("followup_logs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_followup_logs_scheduled_status", ["scheduled_at", "status"], unique=False
        )
        batch_op.create_index(
            "ix_followup_logs_user_template", ["telegram_user_id", "template_id"], unique=True
        )
        batch_op.create_index(batch_op.f("ix_followup_logs_lead_id"), ["lead_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_followup_logs_scheduled_at"), ["scheduled_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_followup_logs_template_id"), ["template_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_followup_logs_telegram_user_id"), ["telegram_user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("followup_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_followup_logs_telegram_user_id"))
        batch_op.drop_index(batch_op.f("ix_followup_logs_template_id"))
        batch_op.drop_index(batch_op.f("ix_followup_logs_scheduled_at"))
        batch_op.drop_index(batch_op.f("ix_followup_logs_lead_id"))
        batch_op.drop_index("ix_followup_logs_user_template")
        batch_op.drop_index("ix_followup_logs_scheduled_status")

    op.drop_table("followup_logs")
    with op.batch_alter_table("followup_templates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_followup_templates_trigger"))
        batch_op.drop_index("ix_followup_templates_lang_active")
        batch_op.drop_index("ix_followup_templates_trigger_active")

    op.drop_table("followup_templates")
