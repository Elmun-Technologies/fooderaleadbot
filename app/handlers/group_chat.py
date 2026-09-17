"""Group chat handler: allow managers to reply to lead cards and chat with leads."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import Message

from app.config import Settings
from app.database.repository import LeadRepository
from app.i18n import t
from app.services.chat_service import ChatService
from app.services.notification import LeadNotifier

logger = logging.getLogger(__name__)

router = Router(name="group_chat")


async def is_manager(
    bot: Any, user_id: int, chat_id: int | None, settings: Settings
) -> bool:
    if user_id in settings.admin_user_ids:
        return True
    if not settings.allow_group_managers or not settings.sales_group_id:
        return False
    # if message is in sales group, allow
    if chat_id and chat_id == settings.sales_group_id:
        return True
    # also check if user is member of sales group via API
    if bot is not None and settings.sales_group_id:
        try:
            member = await bot.get_chat_member(settings.sales_group_id, user_id)
            # status: creator, administrator, member, restricted, left, kicked
            if member.status in ("creator", "administrator", "member"):
                return True
        except Exception:
            pass
    return False


@router.message(F.chat.type.in_({"group", "supergroup"}), F.reply_to_message)
async def reply_to_lead_card(message: Message, **data: Any) -> None:
    """When a manager replies to a lead card in the sales group, forward to the lead."""
    settings: Settings = data["settings"]
    repo: LeadRepository = data["repo"]
    bot = data.get("bot")
    lang = data.get("lang", settings.default_language)

    if not message.from_user:
        return

    # Only handle messages in sales group (or visitor group)
    allowed_chats = {settings.sales_group_id, settings.visitor_group_id}
    if message.chat.id not in allowed_chats:
        return

    if not await is_manager(bot, message.from_user.id, message.chat.id, settings):
        return

    reply_to = message.reply_to_message
    if not reply_to:
        return

    # Find lead by the message being replied to
    lead = await repo.get_lead_by_notify_message(message.chat.id, reply_to.message_id)
    if lead is None:
        # maybe reply_to is not the card but a previous reply? try to find via thread?
        # Search for lead where notify_chat_id matches and the reply is in thread?
        # For simplicity, ignore
        return

    # Extract text/photo/document from manager's message
    text = message.text or message.caption or ""
    photo_file_id = None
    document_file_id = None
    file_name = None

    if message.photo:
        photo_file_id = message.photo[-1].file_id
    if message.document:
        document_file_id = message.document.file_id
        file_name = message.document.file_name

    if not text and not photo_file_id and not document_file_id:
        return

    # Send to lead
    chat_service = ChatService(bot, repo)
    try:
        await chat_service.send_to_user(
            lead.telegram_user_id,
            text=text,
            lead_id=lead.id,
            admin_user_id=message.from_user.id,
            admin_username=message.from_user.username,
            photo_file_id=photo_file_id,
            document_file_id=document_file_id,
            file_name=file_name,
        )
        # Confirm in group
        await message.reply(
            t("chat.sent_to_lead", lang, code=lead.lead_code)
            if "chat.sent_to_lead" in t.__module__ or True
            else f"✅ Sent to {lead.lead_code}"
        )
    except Exception as exc:
        logger.warning("failed to forward group reply to lead %s: %s", lead.id, exc)
        await message.reply(t("err.db", lang) if lang else "Failed to send")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group_analytics_commands(message: Message, **data: Any) -> None:
    """Allow any group member to request quick stats in the group."""
    settings: Settings = data["settings"]
    repo: LeadRepository = data["repo"]
    bot = data.get("bot")
    lang = data.get("lang", settings.default_language)

    if not message.from_user:
        return
    if message.chat.id != settings.sales_group_id:
        return
    if not message.text:
        return

    text = message.text.strip().lower()
    if text not in ("/stats", "/stat", "📊", "/analytics", "/analitika"):
        return

    if not await is_manager(bot, message.from_user.id, message.chat.id, settings):
        await message.reply(t("err.not_manager", lang))
        return

    # Quick stats
    from datetime import datetime, timezone

    from app.handlers.admin import start_of_today

    since = start_of_today(settings.display_timezone)
    today_total = await repo.count_leads(since=since)
    total_completed = await repo.count_leads()
    qualified = await repo.count_leads(classification=["HOT", "WARM"])
    statuses = await repo.status_counts()
    classification = await repo.classification_counts()

    lines = [
        f"📊 <b>FOODERA Leads</b>",
        f"Bugun: {today_total} | Jami: {total_completed}",
        f"HOT: {classification.get('HOT',0)} WARM: {classification.get('WARM',0)} COLD: {classification.get('COLD',0)}",
        f"Qualified: {qualified}",
        f"Pipeline: " + " · ".join(f"{k}={v}" for k, v in statuses.items() if v),
    ]
    await message.reply("\n".join(lines))
