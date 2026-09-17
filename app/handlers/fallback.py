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
    """A plain text message with no active questionnaire: offer funnel or treat as chat."""
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)
    leads = data.get("leads")
    repo = data.get("repo")
    user = data.get("user")
    bot = data.get("bot")

    if leads is not None and user is not None:
        draft = await leads.repo.active_draft(
            user.telegram_user_id, ttl_hours=settings.draft_ttl_hours
        )
        if draft is not None:
            from app.handlers.start import begin_questions

            await begin_questions(message, data, draft, first_step=await leads.resume_step(draft))
            return

        # No draft, but user has completed leads before -> treat as direct chat message
        last_lead = await repo.last_completed(user.telegram_user_id) if repo else None
        if last_lead is not None and repo is not None:
            # Save inbound chat
            from app.services.chat_service import ChatService

            chat_service = ChatService(bot, repo)
            await chat_service.save_inbound(
                user.telegram_user_id,
                text=message.text,
                lead_id=last_lead.id,
                telegram_message_id=message.message_id,
            )
            # Forward to sales group if configured
            if settings.sales_group_id and bot is not None:
                try:
                    forward_text = (
                        f"💬 <b>{last_lead.lead_code}</b> dan xabar:\n\n{message.text}\n\n"
                        f"Javob berish uchun ushbu xabarga reply qiling."
                    )
                    # If lead card exists, reply to it
                    if last_lead.notify_chat_id and last_lead.notify_message_id:
                        await bot.send_message(
                            last_lead.notify_chat_id,
                            forward_text,
                            reply_to_message_id=last_lead.notify_message_id,
                        )
                    else:
                        await bot.send_message(settings.sales_group_id, forward_text)
                except Exception:
                    pass
            await message.answer(t("chat.received", lang))
            return

    await message.answer(
        f"{t('welcome.text', lang)}\n\n{t('info.no_active_form', lang)}",
        reply_markup=start_kb(lang),
    )


@router.message(StateFilter(None), ~F.text, PrivateChat())
async def unsupported_media(message: Message, **data: Any) -> None:
    """Photos / stickers / voice messages outside the form - treat as chat if lead exists."""
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)
    repo = data.get("repo")
    bot = data.get("bot")
    user = data.get("user")

    if repo is not None and user is not None:
        last_lead = await repo.last_completed(user.telegram_user_id)
        if last_lead is not None:
            from app.services.chat_service import ChatService

            photo_file_id = None
            document_file_id = None
            file_name = None
            text = message.caption or ""

            if message.photo:
                photo_file_id = message.photo[-1].file_id
            if message.document:
                document_file_id = message.document.file_id
                file_name = message.document.file_name

            chat_service = ChatService(bot, repo)
            await chat_service.save_inbound(
                user.telegram_user_id,
                text=text,
                lead_id=last_lead.id,
                photo_file_id=photo_file_id,
                document_file_id=document_file_id,
                file_name=file_name,
                telegram_message_id=message.message_id,
            )
            # Forward to group
            if settings.sales_group_id and bot is not None:
                try:
                    caption = f"💬 <b>{last_lead.lead_code}</b> dan media xabar"
                    if text:
                        caption += f":\n\n{text}"
                    if photo_file_id:
                        await bot.send_photo(
                            settings.sales_group_id, photo=photo_file_id, caption=caption
                        )
                    elif document_file_id:
                        await bot.send_document(
                            settings.sales_group_id, document=document_file_id, caption=caption
                        )
                except Exception:
                    pass
            await message.answer(t("chat.received", lang))
            return

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
