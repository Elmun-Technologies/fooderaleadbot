"""``/beydjik`` - fetch the guest badge again (private chats only).

The badge is generated automatically at the end of the visitor funnel; this command is
the recovery path for a guest who lost the picture (new phone, deleted chat, the photo
never arrived because the render failed).  It re-draws the badge from the stored lead -
nothing is cached or persisted, which is the whole reason the feature needs no migration.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import LinkPreviewOptions, Message

from app.config import Settings
from app.database.models import BotUser
from app.filters import PrivateChat
from app.i18n import t
from app.keyboards.inline import start_kb
from app.services.badge_service import is_visitor_lead, send_badge
from app.services.lead_service import LeadService

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = Router(name="badge")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@router.message(Command("beydjik"), PrivateChat())
async def cmd_badge(message: Message, **data: Any) -> None:
    """Send the last finished visitor application as a badge, or explain how to get one."""
    settings: Settings = data["settings"]
    leads: LeadService = data["leads"]
    lang: str = data.get("lang", settings.default_language)
    user: BotUser | None = data.get("user")

    if not settings.visitor_badge_enabled:
        await message.answer(t("badge.disabled", lang), link_preview_options=_NO_PREVIEW)
        return

    lead = await leads.repo.last_completed(user.telegram_user_id) if user is not None else None
    if lead is None or not is_visitor_lead(lead):
        await message.answer(
            t("badge.no_application", lang),
            reply_markup=start_kb(lang),
            link_preview_options=_NO_PREVIEW,
        )
        return

    if not await send_badge(message.bot, lead, lang=lang, chat_id=message.chat.id):
        await message.answer(t("badge.error", lang), link_preview_options=_NO_PREVIEW)
