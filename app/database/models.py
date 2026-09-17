"""SQLAlchemy ORM models (PostgreSQL in production, SQLite for local testing)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "Base",
    "BotUser",
    "Broadcast",
    "BroadcastStatus",
    "ChatDirection",
    "ChatMessage",
    "Classification",
    "FollowUpLog",
    "FollowUpStatus",
    "FollowUpTemplate",
    "FollowUpTrigger",
    "FunnelEvent",
    "Lead",
    "LeadEvent",
    "LeadStatus",
    "LeadType",
    "utcnow",
]

# SQLite has no real BIGINT autoincrement, so ids degrade to INTEGER there.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
BigInt = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class LeadType(StrEnum):
    EXHIBITOR = "exhibitor"
    PARTNER = "partner"
    VISITOR = "visitor"


class Classification(StrEnum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    LOW = "LOW"
    VISITOR = "VISITOR"


class LeadStatus(StrEnum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    NEGOTIATION = "NEGOTIATION"
    BOOKED = "BOOKED"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    CLOSED = "CLOSED"


#: Statuses that must not be "downgraded" by accident (managers can still force via /lead)
LOCKED_STATUSES: frozenset[str] = frozenset({LeadStatus.BOOKED})


class BroadcastStatus(StrEnum):
    DRAFT = "DRAFT"
    SENDING = "SENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class ChatDirection(StrEnum):
    INBOUND = "inbound"  # from lead to admin
    OUTBOUND = "outbound"  # from admin to lead


class FollowUpTrigger(StrEnum):
    DRAFT_ABANDONED = "draft_abandoned"  # started but not finished
    STARTED_NOT_COMPLETED = "started_not_completed"  # /start but no lead
    COMPLETED_EXHIBITOR = "completed_exhibitor"
    COMPLETED_VISITOR = "completed_visitor"
    COMPLETED_PARTNER = "completed_partner"
    HOT_LEAD = "hot_lead"
    WARM_LEAD = "warm_lead"
    COLD_LEAD = "cold_lead"
    STATUS_NEW = "status_new"  # still NEW after X hours
    STATUS_CONTACTED = "status_contacted"
    ALL_COMPLETED = "all_completed"


class FollowUpStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class FunnelEvent(StrEnum):
    STARTED = "STARTED"
    APPLICATION_OPENED = "APPLICATION_OPENED"
    LANGUAGE_SELECTED = "LANGUAGE_SELECTED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    RESUMED = "RESUMED"
    RESTARTED = "RESTARTED"
    INTENT_SELECTED = "INTENT_SELECTED"
    COMPANY_TYPE_SELECTED = "COMPANY_TYPE_SELECTED"
    CATEGORY_SELECTED = "CATEGORY_SELECTED"
    COMPANY_ENTERED = "COMPANY_ENTERED"
    LOCATION_ENTERED = "LOCATION_ENTERED"
    ONLINE_ENTERED = "ONLINE_ENTERED"
    CONTACT_ENTERED = "CONTACT_ENTERED"
    PHONE_ENTERED = "PHONE_ENTERED"
    STAND_SELECTED = "STAND_SELECTED"
    READINESS_SELECTED = "READINESS_SELECTED"
    STEP_SKIPPED = "STEP_SKIPPED"
    COMPLETED = "COMPLETED"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"
    NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
    STATUS_CHANGED = "STATUS_CHANGED"
    LEAD_UPDATED = "LEAD_UPDATED"
    ABANDONED = "ABANDONED"


#: ordered funnel used by /stats
FUNNEL_STEPS: tuple[FunnelEvent, ...] = (
    FunnelEvent.STARTED,
    FunnelEvent.LANGUAGE_SELECTED,
    FunnelEvent.INTENT_SELECTED,
    FunnelEvent.COMPANY_TYPE_SELECTED,
    FunnelEvent.CATEGORY_SELECTED,
    FunnelEvent.COMPANY_ENTERED,
    FunnelEvent.CONTACT_ENTERED,
    FunnelEvent.PHONE_ENTERED,
    FunnelEvent.COMPLETED,
)


class BotUser(Base):
    """Telegram account that interacted with the bot (language + attribution live here)."""

    __tablename__ = "bot_users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInt, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")
    language_explicit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    start_payload: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(32), default="direct", server_default="direct")
    campaign: Mapped[str | None] = mapped_column(String(64))
    creative: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    leads: Mapped[list[Lead]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Lead(Base):
    """One qualification application (exhibitor, partner or visitor)."""

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    lead_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    bot_user_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("bot_users.id", ondelete="SET NULL"), index=True
    )
    user: Mapped[BotUser | None] = relationship(back_populates="leads")

    telegram_user_id: Mapped[int] = mapped_column(BigInt, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    telegram_first_name: Mapped[str | None] = mapped_column(String(128))
    telegram_last_name: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")

    # attribution
    start_payload: Mapped[str | None] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(32), default="direct", server_default="direct")
    campaign: Mapped[str | None] = mapped_column(String(64))
    creative: Mapped[str | None] = mapped_column(String(128))

    # questionnaire answers (canonical slugs, never localized text)
    lead_type: Mapped[str] = mapped_column(
        String(16), default="exhibitor", server_default="exhibitor"
    )
    intent: Mapped[str | None] = mapped_column(String(32), index=True)
    company_type: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(64))
    company_name: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(120))
    online_presence: Mapped[str | None] = mapped_column(String(16))
    website: Mapped[str | None] = mapped_column(String(255))
    instagram: Mapped[str | None] = mapped_column(String(128))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    position: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    preferred_stand_size: Mapped[str | None] = mapped_column(String(16))
    readiness: Mapped[str | None] = mapped_column(String(32))
    business_relation: Mapped[str | None] = mapped_column(String(32))

    # evaluation
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    score_breakdown: Mapped[dict | None] = mapped_column(JSON)
    classification: Mapped[str | None] = mapped_column(String(16), index=True)
    is_high_intent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # pipeline
    lead_status: Mapped[str] = mapped_column(
        String(20), default=LeadStatus.NEW.value, server_default=LeadStatus.NEW.value, index=True
    )
    manager_user_id: Mapped[int | None] = mapped_column(BigInt)
    manager_username: Mapped[str | None] = mapped_column(String(64))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # lifecycle / anti-spam
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", index=True)
    current_step: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # sales group message (needed to edit the card when a manager taps a button)
    notify_chat_id: Mapped[int | None] = mapped_column(BigInt)
    notify_message_id: Mapped[int | None] = mapped_column(Integer)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[LeadEvent]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_leads_classification_created", "classification", "created_at"),
        Index("ix_leads_campaign_created", "campaign", "created_at"),
        Index("ix_leads_user_completed", "telegram_user_id", "completed_at"),
    )

    # -------------------------------------------------------------- helpers
    @property
    def display_name(self) -> str:
        full = " ".join(
            part for part in (self.telegram_first_name, self.telegram_last_name) if part
        )
        return full or (
            f"@{self.telegram_username}" if self.telegram_username else str(self.telegram_user_id)
        )

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    def field_values(self) -> dict[str, object]:
        """Scoring-relevant answers as a plain dict."""
        return {
            "intent": self.intent,
            "company_type": self.company_type,
            "category": self.category,
            "company_name": self.company_name,
            "region": self.region,
            "country": self.country,
            "online_presence": self.online_presence,
            "website": self.website,
            "instagram": self.instagram,
            "contact_name": self.contact_name,
            "position": self.position,
            "phone": self.phone,
            "preferred_stand_size": self.preferred_stand_size,
            "readiness": self.readiness,
            "business_relation": self.business_relation,
            "source": self.source,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Lead id={self.id} code={self.lead_code} classification={self.classification} "
            f"score={self.score} status={self.lead_status}>"
        )


class LeadEvent(Base):
    """Append-only audit + funnel log."""

    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    lead_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    telegram_user_id: Mapped[int | None] = mapped_column(BigInt, index=True)
    event: Mapped[str] = mapped_column(String(48), index=True)
    step: Mapped[str | None] = mapped_column(String(32))
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    lead: Mapped[Lead | None] = relationship(back_populates="events")

    __table_args__ = (Index("ix_lead_events_event_created", "event", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LeadEvent {self.event} lead={self.lead_id}>"


class Broadcast(Base):
    """Mass messaging to leads (rassilka) with optional photo/document."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, default="")
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    document_file_id: Mapped[str | None] = mapped_column(String(255))
    document_url: Mapped[str | None] = mapped_column(String(512))
    document_name: Mapped[str | None] = mapped_column(String(255))

    # targeting filters (JSON for flexibility)
    filter_classification: Mapped[str | None] = mapped_column(String(32))
    filter_status: Mapped[str | None] = mapped_column(String(32))
    filter_source: Mapped[str | None] = mapped_column(String(32))
    filter_campaign: Mapped[str | None] = mapped_column(String(128))
    filter_lead_type: Mapped[str | None] = mapped_column(String(16))
    filter_language: Mapped[str | None] = mapped_column(String(8))

    status: Mapped[str] = mapped_column(
        String(16), default=BroadcastStatus.DRAFT.value, server_default=BroadcastStatus.DRAFT.value
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_by_id: Mapped[int | None] = mapped_column(BigInt)
    created_by_username: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Broadcast id={self.id} status={self.status} total={self.total_count}>"


class ChatMessage(Base):
    """Direct chat between admin and lead (bidirectional)."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    lead_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInt, index=True)
    direction: Mapped[str] = mapped_column(String(16), default=ChatDirection.INBOUND.value)

    text: Mapped[str | None] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    document_file_id: Mapped[str | None] = mapped_column(String(255))
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(32))

    # admin who sent (for outbound)
    admin_user_id: Mapped[int | None] = mapped_column(BigInt)
    admin_username: Mapped[str | None] = mapped_column(String(64))

    # telegram message ids for tracking
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    reply_to_message_id: Mapped[int | None] = mapped_column(Integer)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    lead: Mapped[Lead | None] = relationship(backref="chat_messages")

    __table_args__ = (
        Index("ix_chat_messages_user_created", "telegram_user_id", "created_at"),
        Index("ix_chat_messages_lead_created", "lead_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatMessage id={self.id} user={self.telegram_user_id} dir={self.direction}>"


class FollowUpTemplate(Base):
    """Marketing follow-up template - proactive messages inside bot."""

    __tablename__ = "followup_templates"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    trigger: Mapped[str] = mapped_column(String(32), index=True)  # FollowUpTrigger
    delay_hours: Mapped[int] = mapped_column(Integer, default=1)  # after trigger
    language: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")

    text: Mapped[str] = mapped_column(Text, default="")
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    document_file_id: Mapped[str | None] = mapped_column(String(255))
    document_name: Mapped[str | None] = mapped_column(String(255))

    # targeting filters
    filter_classification: Mapped[str | None] = mapped_column(String(32))
    filter_lead_type: Mapped[str | None] = mapped_column(String(16))
    filter_source: Mapped[str | None] = mapped_column(String(32))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # higher first

    # tracking
    total_sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    logs: Mapped[list[FollowUpLog]] = relationship(back_populates="template", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_followup_templates_trigger_active", "trigger", "is_active"),
        Index("ix_followup_templates_lang_active", "language", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FollowUpTemplate id={self.id} trigger={self.trigger} lang={self.language} delay={self.delay_hours}h>"


class FollowUpLog(Base):
    """Log of sent follow-ups to avoid duplicate spam."""

    __tablename__ = "followup_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        BigInt, ForeignKey("followup_templates.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInt, index=True)
    bot_user_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("bot_users.id", ondelete="SET NULL"))

    status: Mapped[str] = mapped_column(String(16), default=FollowUpStatus.PENDING.value)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    template: Mapped[FollowUpTemplate] = relationship(back_populates="logs")
    lead: Mapped[Lead | None] = relationship(backref="followup_logs")

    __table_args__ = (
        Index("ix_followup_logs_user_template", "telegram_user_id", "template_id", unique=True),
        Index("ix_followup_logs_scheduled_status", "scheduled_at", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FollowUpLog template={self.template_id} user={self.telegram_user_id} status={self.status}>"
