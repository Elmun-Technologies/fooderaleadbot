"""Visitor funnel (Q1 = "Mehmon sifatida tashrif buyurmoqchiman").

Visitors are *not* exhibitors: no stand, no pricing, no scoring pressure.  They answer
four questions (name, phone, city, relation to the industry) and are stored with
``lead_type = visitor``.  Their application never reaches the exhibitor sales group -
only the optional ``VISITOR_GROUP_ID``.

Registering this router **before** the qualification router lets us intercept
``q:intent:visitor`` for the visitor greeting; every remaining question is handled by
the shared engine, driven by ``VISITOR_PATH`` from :mod:`app.flow`.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.flow import VISITOR_PATH
from app.handlers.engine import ask, require_context
from app.i18n import t
from app.options import Intent

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = Router(name="visitor")

VISITOR_FIRST_STEP = VISITOR_PATH[1]  # "visitor_name"


@router.callback_query(F.data == f"q:intent:{Intent.VISITOR}")
async def visitor_entry(callback: CallbackQuery, **data: Any) -> None:
    """Save the intent, explain the short flow, then ask the first visitor question."""
    ctx = await require_context(callback, data)
    if ctx is None:
        return

    updated = await ctx.leads.save_answer(ctx.lead, "intent", {"intent": Intent.VISITOR.value})
    ctx.lead = updated

    with suppress(TelegramBadRequest):
        await callback.answer()

    if callback.message is not None:
        try:
            await callback.message.answer(t("visitor.intro", ctx.lang))
        except TelegramBadRequest:  # pragma: no cover
            logger.debug("visitor intro not delivered")

    await ask(ctx, VISITOR_FIRST_STEP)
