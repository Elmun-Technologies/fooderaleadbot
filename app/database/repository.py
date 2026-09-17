"""Data access layer.

All queries go through :class:`LeadRepository` - handlers and services never build
SQL themselves, and every lookup uses bound parameters (no string interpolation).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    BotUser,
    Broadcast,
    BroadcastStatus,
    ChatDirection,
    ChatMessage,
    Classification,
    FunnelEvent,
    Lead,
    LeadEvent,
    LeadStatus,
    LeadType,
    utcnow,
)

__all__ = ["LeadRepository"]

_QUALIFIED: tuple[str, ...] = (Classification.HOT.value, Classification.WARM.value)


class LeadRepository:
    """Async repository for users, leads, funnel events and admin statistics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ users
    async def get_user(self, telegram_user_id: int) -> BotUser | None:
        result = await self.session.execute(
            select(BotUser).where(BotUser.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_user(
        self,
        telegram_user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> BotUser:
        user = await self.get_user(telegram_user_id)
        if user is not None:
            if username is not None:
                user.username = username
            if first_name is not None:
                user.first_name = first_name
            if last_name is not None:
                user.last_name = last_name
            user.last_seen_at = utcnow()
            await self.session.commit()
            return user

        user = BotUser(
            telegram_user_id=telegram_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            **(defaults or {}),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_user(self, user: BotUser, **values: Any) -> BotUser:
        for key, value in values.items():
            setattr(user, key, value)
        user.updated_at = utcnow()
        await self.session.commit()
        return user

    # ------------------------------------------------------------------ leads
    async def create_lead(self, *, lead_code_prefix: str = "FD", **values: Any) -> Lead:
        """Insert a draft lead and assign its public code (``FD000123``).

        The code is derived from the primary key, so it needs two round trips: a
        throw-away unique placeholder on INSERT, then the real code.  That keeps the
        code short, human-readable and collision-free without a sequence object.
        """
        placeholder = f"{lead_code_prefix}-PENDING-{uuid4().hex[:12]}"
        lead = Lead(is_draft=True, lead_code=placeholder, **values)
        self.session.add(lead)
        await self.session.flush()
        lead.lead_code = f"{lead_code_prefix}{lead.id:06d}"
        await self.session.commit()
        await self.session.refresh(lead)
        return lead

    async def get_lead(self, lead_id: int) -> Lead | None:
        return await self.session.get(Lead, lead_id)

    async def get_lead_by_code(self, code: str) -> Lead | None:
        result = await self.session.execute(
            select(Lead).where(Lead.lead_code == code.strip().upper())
        )
        return result.scalar_one_or_none()

    async def find_lead(self, identifier: str | int) -> Lead | None:
        """Resolve ``123`` or ``FD000123`` (used by admin commands)."""
        text = str(identifier).strip().lstrip("#")
        if text.isdigit():
            return await self.get_lead(int(text))
        return await self.get_lead_by_code(text)

    async def update_lead(self, lead_id: int, **values: Any) -> Lead | None:
        """Update through the ORM object so the identity map can never go stale."""
        lead = await self.session.get(Lead, lead_id)
        if lead is None:
            return None
        columns = Lead.__table__.columns
        for key, value in values.items():
            if key in columns:
                setattr(lead, key, value)
        if "updated_at" not in values:
            lead.updated_at = utcnow()  # explicit timestamps (backfills, tests) win
        await self.session.commit()
        return lead

    async def active_draft(self, telegram_user_id: int, *, ttl_hours: int = 72) -> Lead | None:
        """Latest unfinished application - used to offer "continue" after a restart."""
        since = utcnow() - timedelta(hours=ttl_hours)
        result = await self.session.execute(
            select(Lead)
            .where(
                Lead.telegram_user_id == telegram_user_id,
                Lead.is_draft.is_(True),
                Lead.created_at >= since,
            )
            .order_by(Lead.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def recent_completed(
        self, telegram_user_id: int, *, within_hours: int = 24
    ) -> Lead | None:
        """Last finished application inside the anti-spam window."""
        since = utcnow() - timedelta(hours=within_hours)
        result = await self.session.execute(
            select(Lead)
            .where(
                Lead.telegram_user_id == telegram_user_id,
                Lead.completed_at.is_not(None),
                Lead.completed_at >= since,
            )
            .order_by(Lead.completed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def last_completed(self, telegram_user_id: int) -> Lead | None:
        result = await self.session.execute(
            select(Lead)
            .where(Lead.telegram_user_id == telegram_user_id, Lead.completed_at.is_not(None))
            .order_by(Lead.completed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def abandon_draft(self, lead_id: int) -> None:
        await self.update_lead(lead_id, is_draft=False, current_step=None)

    async def list_leads(
        self,
        *,
        classification: Sequence[str] | str | None = None,
        lead_type: str | None = None,
        since: datetime | None = None,
        campaign: str | None = None,
        source: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
        only_completed: bool = True,
    ) -> Sequence[Lead]:
        stmt: Select = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        conditions = self._lead_filters(
            classification=classification,
            lead_type=lead_type,
            since=since,
            campaign=campaign,
            source=source,
            status=status,
            only_completed=only_completed,
        )
        for condition in conditions:
            stmt = stmt.where(condition)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    def _lead_filters(
        *,
        classification: Sequence[str] | str | None,
        lead_type: str | None,
        since: datetime | None,
        campaign: str | None,
        source: str | None,
        status: str | None,
        only_completed: bool,
    ) -> list[Any]:
        conditions: list[Any] = []
        if only_completed:
            conditions.append(Lead.completed_at.is_not(None))
        if classification:
            values = [classification] if isinstance(classification, str) else list(classification)
            conditions.append(Lead.classification.in_(values))
        if lead_type:
            conditions.append(Lead.lead_type == lead_type)
        if since:
            conditions.append(Lead.created_at >= since)
        if campaign:
            conditions.append(Lead.campaign == campaign)
        if source:
            conditions.append(Lead.source == source)
        if status:
            conditions.append(Lead.lead_status == status)
        return conditions

    async def count_leads(
        self,
        *,
        classification: Sequence[str] | str | None = None,
        lead_type: str | None = None,
        since: datetime | None = None,
        campaign: str | None = None,
        source: str | None = None,
        status: str | None = None,
        only_completed: bool = True,
    ) -> int:
        conditions = self._lead_filters(
            classification=classification,
            lead_type=lead_type,
            since=since,
            campaign=campaign,
            source=source,
            status=status,
            only_completed=only_completed,
        )
        stmt = select(func.count()).select_from(Lead)
        for condition in conditions:
            stmt = stmt.where(condition)
        return int((await self.session.execute(stmt)).scalar_one())

    async def set_status(
        self,
        lead_id: int,
        status: str,
        *,
        manager_user_id: int | None = None,
        manager_username: str | None = None,
    ) -> Lead | None:
        return await self.update_lead(
            lead_id,
            lead_status=status,
            manager_user_id=manager_user_id,
            manager_username=manager_username,
            status_changed_at=utcnow(),
        )

    async def attach_notification(self, lead_id: int, *, chat_id: int, message_id: int) -> None:
        await self.update_lead(
            lead_id, notify_chat_id=chat_id, notify_message_id=message_id, notified_at=utcnow()
        )

    # ----------------------------------------------------------------- events
    async def add_event(
        self,
        event: FunnelEvent | str,
        *,
        lead_id: int | None = None,
        telegram_user_id: int | None = None,
        step: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> LeadEvent:
        row = LeadEvent(
            event=str(event),
            lead_id=lead_id,
            telegram_user_id=telegram_user_id,
            step=step,
            data=data,
        )
        self.session.add(row)
        await self.session.commit()
        return row

    async def events_for_lead(self, lead_id: int) -> Sequence[LeadEvent]:
        result = await self.session.execute(
            select(LeadEvent)
            .where(LeadEvent.lead_id == lead_id)
            .order_by(LeadEvent.created_at.asc(), LeadEvent.id.asc())
        )
        return result.scalars().all()

    # ------------------------------------------------------------------ stats
    async def classification_counts(
        self, *, since: datetime | None = None, exclude_visitors: bool = False
    ) -> dict[str, int]:
        conditions = [Lead.completed_at.is_not(None)]
        if since:
            conditions.append(Lead.created_at >= since)
        if exclude_visitors:
            conditions.append(Lead.lead_type != LeadType.VISITOR.value)
        stmt = (
            select(Lead.classification, func.count())
            .where(and_(*conditions))
            .group_by(Lead.classification)
        )
        rows = (await self.session.execute(stmt)).all()
        counts = {str(value or "UNKNOWN"): int(count) for value, count in rows}
        for name in (item.value for item in Classification):
            counts.setdefault(name, 0)
        return counts

    async def visitor_count(self, *, since: datetime | None = None) -> int:
        conditions = [Lead.lead_type == LeadType.VISITOR.value, Lead.completed_at.is_not(None)]
        if since:
            conditions.append(Lead.created_at >= since)
        stmt = select(func.count()).select_from(Lead).where(and_(*conditions))
        return int((await self.session.execute(stmt)).scalar_one())

    async def started_count(self, *, since: datetime | None = None) -> int:
        """Unique users who began the flow (funnel top)."""
        conditions = [LeadEvent.event == FunnelEvent.STARTED.value]
        if since:
            conditions.append(LeadEvent.created_at >= since)
        stmt = select(func.count(func.distinct(LeadEvent.telegram_user_id))).where(
            and_(*conditions)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def funnel_counts(self, *, since: datetime | None = None) -> dict[str, int]:
        """Unique users reaching each funnel step - shows where leads drop off."""
        conditions = [LeadEvent.event.in_([step.value for step in FunnelEvent])]
        if since:
            conditions.append(LeadEvent.created_at >= since)
        stmt = (
            select(LeadEvent.event, func.count(func.distinct(LeadEvent.telegram_user_id)))
            .where(and_(*conditions))
            .group_by(LeadEvent.event)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(event): int(count) for event, count in rows}

    async def status_counts(self, *, since: datetime | None = None) -> dict[str, int]:
        conditions = [Lead.completed_at.is_not(None)]
        if since:
            conditions.append(Lead.created_at >= since)
        stmt = (
            select(Lead.lead_status, func.count())
            .where(and_(*conditions))
            .group_by(Lead.lead_status)
        )
        rows = (await self.session.execute(stmt)).all()
        counts = {str(value or LeadStatus.NEW.value): int(count) for value, count in rows}
        for name in (item.value for item in LeadStatus):
            counts.setdefault(name, 0)
        return counts

    async def source_breakdown(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Performance per ``source / campaign`` pair."""
        stmt = (
            select(
                Lead.source,
                Lead.campaign,
                func.count().label("total"),
                func.sum(case((Lead.completed_at.is_not(None), 1), else_=0)).label("completed"),
                func.sum(case((Lead.classification.in_(_QUALIFIED), 1), else_=0)).label(
                    "qualified"
                ),
                func.sum(case((Lead.classification == Classification.HOT.value, 1), else_=0)).label(
                    "hot"
                ),
                func.sum(case((Lead.lead_type == LeadType.VISITOR.value, 1), else_=0)).label(
                    "visitors"
                ),
                func.max(Lead.created_at).label("last_at"),
            )
            .group_by(Lead.source, Lead.campaign)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "source": row.source or "direct",
                "campaign": row.campaign,
                "total": int(row.total or 0),
                "completed": int(row.completed or 0),
                "qualified": int(row.qualified or 0),
                "hot": int(row.hot or 0),
                "visitors": int(row.visitors or 0),
                "last_at": row.last_at,
            }
            for row in rows
        ]

    async def payload_breakdown(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Performance per raw ``start_payload`` (the Telegram Ads creative level)."""
        stmt = (
            select(
                Lead.start_payload,
                Lead.creative,
                func.count().label("total"),
                func.sum(case((Lead.completed_at.is_not(None), 1), else_=0)).label("completed"),
                func.sum(case((Lead.classification.in_(_QUALIFIED), 1), else_=0)).label(
                    "qualified"
                ),
                func.sum(case((Lead.lead_type == LeadType.VISITOR.value, 1), else_=0)).label(
                    "visitors"
                ),
            )
            .where(Lead.start_payload.is_not(None))
            .group_by(Lead.start_payload, Lead.creative)
            .order_by(func.count().desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "start_payload": row.start_payload,
                "creative": row.creative,
                "total": int(row.total or 0),
                "completed": int(row.completed or 0),
                "qualified": int(row.qualified or 0),
                "visitors": int(row.visitors or 0),
            }
            for row in rows
        ]

    async def average_score(self, *, since: datetime | None = None) -> float:
        conditions = [Lead.completed_at.is_not(None), Lead.lead_type != LeadType.VISITOR.value]
        if since:
            conditions.append(Lead.created_at >= since)
        stmt = select(func.avg(Lead.score)).where(and_(*conditions))
        value = (await self.session.execute(stmt)).scalar()
        return round(float(value), 1) if value else 0.0

    async def mark_status_if_current(
        self, lead_id: int, expected: str, values: dict[str, Any]
    ) -> bool:
        """Compare-and-set on the status: prevents two managers racing on the same lead."""
        result = await self.session.execute(
            update(Lead).where(Lead.id == lead_id, Lead.lead_status == expected).values(**values)
        )
        await self.session.commit()
        # a bulk UPDATE bypasses the identity map in both directions: reload the row, so the
        # caller never reads a stale status - neither after winning nor after losing the race
        await self.session.execute(
            select(Lead).where(Lead.id == lead_id).execution_options(populate_existing=True)
        )
        return bool(result.rowcount)

    async def stale_drafts(self, *, older_than_hours: int) -> Sequence[Lead]:
        cutoff = utcnow() - timedelta(hours=older_than_hours)
        stmt = (
            select(Lead)
            .where(
                and_(
                    Lead.is_draft.is_(True),
                    or_(Lead.updated_at < cutoff, Lead.updated_at.is_(None)),
                )
            )
            .limit(200)
        )
        return (await self.session.execute(stmt)).scalars().all()

    # --------------------------------------------------------------- broadcasts
    async def create_broadcast(self, **values: Any) -> Broadcast:
        row = Broadcast(**values)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get_broadcast(self, broadcast_id: int) -> Broadcast | None:
        return await self.session.get(Broadcast, broadcast_id)

    async def list_broadcasts(self, *, limit: int = 50, offset: int = 0) -> Sequence[Broadcast]:
        result = await self.session.execute(
            select(Broadcast).order_by(Broadcast.created_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def update_broadcast(self, broadcast_id: int, **values: Any) -> Broadcast | None:
        row = await self.session.get(Broadcast, broadcast_id)
        if row is None:
            return None
        for k, v in values.items():
            setattr(row, k, v)
        await self.session.commit()
        return row

    async def count_broadcasts(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Broadcast))
        return int(result.scalar_one())

    # --------------------------------------------------------------- chat
    async def add_chat_message(self, **values: Any) -> ChatMessage:
        row = ChatMessage(**values)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_chat_messages(
        self, *, telegram_user_id: int | None = None, lead_id: int | None = None, limit: int = 100
    ) -> Sequence[ChatMessage]:
        stmt = select(ChatMessage).order_by(ChatMessage.created_at.asc())
        if telegram_user_id is not None:
            stmt = stmt.where(ChatMessage.telegram_user_id == telegram_user_id)
        if lead_id is not None:
            stmt = stmt.where(ChatMessage.lead_id == lead_id)
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_lead_by_notify_message(self, chat_id: int, message_id: int) -> Lead | None:
        result = await self.session.execute(
            select(Lead).where(Lead.notify_chat_id == chat_id, Lead.notify_message_id == message_id)
        )
        return result.scalar_one_or_none()

    async def get_chat_history(self, telegram_user_id: int, limit: int = 200) -> Sequence[ChatMessage]:
        result = await self.session.execute(
            select(ChatMessage)
            .where(ChatMessage.telegram_user_id == telegram_user_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def unread_chat_count(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.direction == ChatDirection.INBOUND.value, ChatMessage.is_read.is_(False))
        )
        return int(result.scalar_one())

    async def mark_chat_read(self, telegram_user_id: int) -> None:
        await self.session.execute(
            update(ChatMessage)
            .where(
                ChatMessage.telegram_user_id == telegram_user_id,
                ChatMessage.direction == ChatDirection.INBOUND.value,
                ChatMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self.session.commit()

    async def list_recent_chats(self, *, limit: int = 50) -> list[dict[str, Any]]:
        # latest message per user
        subq = (
            select(
                ChatMessage.telegram_user_id,
                func.max(ChatMessage.created_at).label("last_at"),
                func.count().label("total"),
                func.sum(case((ChatMessage.is_read.is_(False), 1), else_=0)).label("unread"),
            )
            .group_by(ChatMessage.telegram_user_id)
            .subquery()
        )
        stmt = (
            select(
                subq.c.telegram_user_id,
                subq.c.last_at,
                subq.c.total,
                subq.c.unread,
                Lead.id.label("lead_id"),
                Lead.lead_code,
                Lead.company_name,
                Lead.contact_name,
                Lead.telegram_username,
            )
            .outerjoin(Lead, Lead.telegram_user_id == subq.c.telegram_user_id)
            .order_by(subq.c.last_at.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            {
                "telegram_user_id": r.telegram_user_id,
                "last_at": r.last_at,
                "total": int(r.total or 0),
                "unread": int(r.unread or 0),
                "lead_id": r.lead_id,
                "lead_code": r.lead_code,
                "company_name": r.company_name,
                "contact_name": r.contact_name,
                "telegram_username": r.telegram_username,
            }
            for r in rows
        ]

    async def search_leads(
        self, query: str, *, limit: int = 20
    ) -> Sequence[Lead]:
        like = f"%{query.strip()}%"
        stmt = (
            select(Lead)
            .where(
                or_(
                    Lead.company_name.ilike(like),
                    Lead.contact_name.ilike(like),
                    Lead.phone.ilike(like),
                    Lead.lead_code.ilike(like),
                    Lead.telegram_username.ilike(like),
                    Lead.telegram_first_name.ilike(like),
                )
            )
            .order_by(Lead.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def export_leads(
        self,
        *,
        classification: Sequence[str] | str | None = None,
        lead_type: str | None = None,
        since: datetime | None = None,
        campaign: str | None = None,
        source: str | None = None,
        status: str | None = None,
        only_completed: bool = False,
    ) -> Sequence[Lead]:
        conditions = self._lead_filters(
            classification=classification,
            lead_type=lead_type,
            since=since,
            campaign=campaign,
            source=source,
            status=status,
            only_completed=only_completed,
        )
        stmt = select(Lead).order_by(Lead.created_at.desc())
        for cond in conditions:
            stmt = stmt.where(cond)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def leads_for_broadcast(self, broadcast: Broadcast) -> Sequence[Lead]:
        conditions: list[Any] = [Lead.completed_at.is_not(None)]
        if broadcast.filter_classification:
            conditions.append(Lead.classification == broadcast.filter_classification)
        if broadcast.filter_status:
            conditions.append(Lead.lead_status == broadcast.filter_status)
        if broadcast.filter_source:
            conditions.append(Lead.source == broadcast.filter_source)
        if broadcast.filter_campaign:
            conditions.append(Lead.campaign == broadcast.filter_campaign)
        if broadcast.filter_lead_type:
            conditions.append(Lead.lead_type == broadcast.filter_lead_type)
        if broadcast.filter_language:
            conditions.append(Lead.language == broadcast.filter_language)
        stmt = select(Lead).where(and_(*conditions)).order_by(Lead.id.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()
