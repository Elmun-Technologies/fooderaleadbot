"""FOODERA lead bot - initial schema.

Creates ``bot_users`` (profile + Telegram Ads attribution), ``leads`` (the
qualification application + scoring/pipeline state) and ``lead_events``
(funnel + audit trail).

Revision ID: 0001
Revises: None
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_users",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "telegram_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=8), server_default="uz", nullable=False),
        sa.Column("language_explicit", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("start_payload", sa.String(length=160), nullable=True),
        sa.Column("source", sa.String(length=32), server_default="direct", nullable=False),
        sa.Column("campaign", sa.String(length=64), nullable=True),
        sa.Column("creative", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bot_users", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_bot_users_telegram_user_id"), ["telegram_user_id"], unique=True
        )

    op.create_table(
        "leads",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("lead_code", sa.String(length=32), nullable=False),
        sa.Column(
            "bot_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column(
            "telegram_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column("telegram_username", sa.String(length=64), nullable=True),
        sa.Column("telegram_first_name", sa.String(length=128), nullable=True),
        sa.Column("telegram_last_name", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=8), server_default="uz", nullable=False),
        sa.Column("start_payload", sa.String(length=160), nullable=True),
        sa.Column("source", sa.String(length=32), server_default="direct", nullable=False),
        sa.Column("campaign", sa.String(length=64), nullable=True),
        sa.Column("creative", sa.String(length=128), nullable=True),
        sa.Column("lead_type", sa.String(length=16), server_default="exhibitor", nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column("company_type", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("company_name", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("online_presence", sa.String(length=16), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("instagram", sa.String(length=128), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("position", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("preferred_stand_size", sa.String(length=16), nullable=True),
        sa.Column("readiness", sa.String(length=32), nullable=True),
        sa.Column("business_relation", sa.String(length=32), nullable=True),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=True),
        sa.Column("classification", sa.String(length=16), nullable=True),
        sa.Column("is_high_intent", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("lead_status", sa.String(length=20), server_default="NEW", nullable=False),
        sa.Column(
            "manager_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("manager_username", sa.String(length=64), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_draft", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "notify_chat_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("notify_message_id", sa.Integer(), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["bot_user_id"], ["bot_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_leads_bot_user_id"), ["bot_user_id"], unique=False)
        batch_op.create_index("ix_leads_campaign_created", ["campaign", "created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_leads_classification"), ["classification"], unique=False
        )
        batch_op.create_index(
            "ix_leads_classification_created", ["classification", "created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_leads_intent"), ["intent"], unique=False)
        batch_op.create_index(batch_op.f("ix_leads_is_draft"), ["is_draft"], unique=False)
        batch_op.create_index(batch_op.f("ix_leads_lead_code"), ["lead_code"], unique=True)
        batch_op.create_index(batch_op.f("ix_leads_lead_status"), ["lead_status"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_leads_telegram_user_id"), ["telegram_user_id"], unique=False
        )
        batch_op.create_index(
            "ix_leads_user_completed", ["telegram_user_id", "completed_at"], unique=False
        )

    op.create_table(
        "lead_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("lead_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column(
            "telegram_user_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True
        ),
        sa.Column("event", sa.String(length=48), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lead_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_lead_events_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_lead_events_event"), ["event"], unique=False)
        batch_op.create_index("ix_lead_events_event_created", ["event", "created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_lead_events_lead_id"), ["lead_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_lead_events_telegram_user_id"), ["telegram_user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("lead_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lead_events_telegram_user_id"))
        batch_op.drop_index(batch_op.f("ix_lead_events_lead_id"))
        batch_op.drop_index("ix_lead_events_event_created")
        batch_op.drop_index(batch_op.f("ix_lead_events_event"))
        batch_op.drop_index(batch_op.f("ix_lead_events_created_at"))

    op.drop_table("lead_events")
    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_index("ix_leads_user_completed")
        batch_op.drop_index(batch_op.f("ix_leads_telegram_user_id"))
        batch_op.drop_index(batch_op.f("ix_leads_lead_status"))
        batch_op.drop_index(batch_op.f("ix_leads_lead_code"))
        batch_op.drop_index(batch_op.f("ix_leads_is_draft"))
        batch_op.drop_index(batch_op.f("ix_leads_intent"))
        batch_op.drop_index("ix_leads_classification_created")
        batch_op.drop_index(batch_op.f("ix_leads_classification"))
        batch_op.drop_index("ix_leads_campaign_created")
        batch_op.drop_index(batch_op.f("ix_leads_bot_user_id"))

    op.drop_table("leads")
    with op.batch_alter_table("bot_users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_bot_users_telegram_user_id"))

    op.drop_table("bot_users")
