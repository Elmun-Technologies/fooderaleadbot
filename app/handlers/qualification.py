"""Exhibitor funnel wiring.

The questionnaire itself is driven by :mod:`app.handlers.engine` (one generic handler
per *kind* of answer, not per question), so this module is only the router wiring:

* ``q:<step>:<value>``  - inline choices (intent, company type, category, region,
  online presence, stand size, readiness, visitor answers);
* ``cat:page:<n>``      - pagination of the 16 FOODERA directions;
* ``nav:back|skip``     - navigation;
* free text and ``📱 share contact`` answers.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.handlers.engine import (
    handle_category_page,
    handle_choice,
    handle_contact_share,
    handle_nav,
    handle_text,
)
from app.i18n import t
from app.keyboards.inline import CAT_PAGE_PREFIX, CHOICE_PREFIX, NAV_PREFIX
from app.states import FormState

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = Router(name="qualification")


@router.callback_query(F.data.startswith(f"{CHOICE_PREFIX}:"))
async def inline_choice(callback: CallbackQuery, **data: Any) -> None:
    await handle_choice(callback, data)


@router.callback_query(F.data.startswith(f"{CAT_PAGE_PREFIX}:"))
async def category_page(callback: CallbackQuery, **data: Any) -> None:
    await handle_category_page(callback, data)


@router.callback_query(F.data.startswith(f"{NAV_PREFIX}:"))
async def navigation(callback: CallbackQuery, **data: Any) -> None:
    await handle_nav(callback, data)


@router.message(FormState.filling, F.contact)
async def contact_shared(message: Message, **data: Any) -> None:
    await handle_contact_share(message, data)


@router.message(FormState.filling, F.text & ~F.command)
async def text_answer(message: Message, **data: Any) -> None:
    await handle_text(message, data)


@router.message(FormState.filling, ~F.text & ~F.contact)
async def unsupported_answer(message: Message, **data: Any) -> None:
    """Photos, stickers, voice messages - politely keep the user on the question."""
    lang: str = data.get("lang", data["settings"].default_language)
    await message.answer(t("err.use_buttons", lang))
