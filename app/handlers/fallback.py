"""Everything that does not fit the funnel: unknown commands, stale buttons, media
messages, and the global error handler that keeps one bad update from killing polling.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, ErrorEvent, LinkPreviewOptions, Message
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.filters import PrivateChat
from app.i18n import t
from app.keyboards.inline import start_kb

__all__ = ["on_error", "router"]

logger = logging.getLogger(__name__)

router = Router(name="fallback")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@router.callback_query(F.data == "noop")
async def closed_lead_button(callback: CallbackQuery) -> None:
    """Buttons on closed lead cards are replaced by an info button - answer the tap."""
    await callback.answer()


@router.callback_query()
async def stale_callback(callback: CallbackQuery, **data: Any) -> None:
    """Any other callback: the question has already been answered (or the bot restarted)."""
    lang: str = data.get(
        "lang", data.get("settings").default_language if data.get("settings") else "uz"
    )
    with suppress(TelegramBadRequest):  # the query may simply be too old
        await callback.answer(t("err.stale_callback", lang))


@router.message(F.text.startswith("/"), PrivateChat())
async def unknown_command(message: Message, **data: Any) -> None:
    """Any slash command we do not implement (including admin commands from strangers)."""
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)
    await message.answer(t("help.text", lang), link_preview_options=_NO_PREVIEW)


@router.message(StateFilter(None), F.text & ~F.command, PrivateChat())
async def message_outside_flow(message: Message, **data: Any) -> None:
    """A plain text message with no active questionnaire: offer the funnel again."""
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)
    leads = data.get("leads")
    user = data.get("user")

    if leads is not None and user is not None:
        draft = await leads.repo.active_draft(
            user.telegram_user_id, ttl_hours=settings.draft_ttl_hours
        )
        if draft is not None:
            # local import: start.py and fallback.py are sibling routers of the same package
            from app.handlers.start import begin_questions

            await begin_questions(message, data, draft, first_step=await leads.resume_step(draft))
            return

    await message.answer(
        f"{t('welcome.text', lang)}\n\n{t('info.no_active_form', lang)}",
        reply_markup=start_kb(lang),
    )


@router.message(StateFilter(None), ~F.text, PrivateChat())
async def unsupported_media(message: Message, **data: Any) -> None:
    """Photos / stickers / voice messages outside the form."""
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)
    await message.answer(t("err.use_buttons", lang))


async def on_error(event: ErrorEvent, **data: Any) -> None:
    """Last line of defence: log with context (never with secrets), tell the user, keep polling.

    aiogram wraps every failed update into an :class:`ErrorEvent`; handling it here means
    one broken update can never kill the polling loop - important while a bot restart
    lands in the middle of a lead's answers.
    """
    settings: Settings | None = data.get("settings")
    lang = data.get("lang", settings.default_language if settings else "uz")
    update = getattr(event, "update", None)
    exception: BaseException = getattr(event, "exception", event)  # type: ignore[assignment]
    message = getattr(update, "message", None)
    callback = getattr(update, "callback_query", None)
    target: Message | CallbackQuery | None = message or callback

    extra = {
        "update_type": type(update).__name__ if update is not None else None,
        "user_id": getattr(getattr(update, "from_user", None), "id", None),
        "chat_id": getattr(getattr(message, "chat", None), "id", None),
        "callback_data": getattr(callback, "data", None),
    }
    if isinstance(exception, SQLAlchemyError):
        logger.error("database error while handling an update", exc_info=exception, extra=extra)
    else:
        logger.exception("unhandled error", extra=extra)

    if isinstance(target, CallbackQuery):
        with suppress(TelegramBadRequest):  # the query is too old to answer
            await target.answer(t("err.unknown", lang))
        return

    if isinstance(target, Message):
        try:
            key = "err.db" if isinstance(exception, SQLAlchemyError) else "err.unknown"
            await target.answer(t(key, lang))
        except TelegramBadRequest:  # pragma: no cover - the user left the chat
            pass
