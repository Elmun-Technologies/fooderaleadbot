"""Entry points: /start (with Telegram Ads deep links), /help, /restart, anti-spam gate."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database.models import BotUser, FunnelEvent
from app.filters import PrivateChat
from app.flow import STEPS
from app.handlers.engine import Context, ask
from app.i18n import t
from app.keyboards.inline import prompt_kb, start_kb
from app.services.lead_service import BeginOutcome, LeadService
from app.states import FormState
from app.utils.text import esc

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = Router(name="start")


def parse_start_argument(message: Message) -> str | None:
    """Everything after ``?start=`` in the deep link (``tgads_foodera_uz_01``)."""
    text = (message.text or "").strip()
    if " " not in text:
        return None
    return text.split(" ", 1)[1].strip() or None


@router.message(CommandStart(), PrivateChat())
async def cmd_start(message: Message, **data: Any) -> None:
    """Welcome, language gate, attribution capture and anti-spam check."""
    leads: LeadService = data["leads"]
    state: FSMContext = data["state"]
    from app.services.source_tracking import parse_start_payload

    source = parse_start_payload(parse_start_argument(message))
    user = await leads.ensure_user(
        message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        telegram_language=message.from_user.language_code,
        source=source,
    )
    if source.start_payload:
        user = await leads.update_attribution(user, source)

    await leads.repo.add_event(
        FunnelEvent.STARTED,
        telegram_user_id=user.telegram_user_id,
        data=source.as_dict(),
    )
    await state.clear()

    if not user.language_explicit:
        # local import: language.py answers the choice by calling show_welcome() here
        from app.handlers.language import ask_language

        await ask_language(message, data, user)
        return

    await show_welcome(message, data, user)


async def show_welcome(message: Message, data: dict, user: BotUser) -> None:
    """Event card + single CTA. Deliberately short: the funnel is the product."""
    settings: Settings = data["settings"]
    leads: LeadService = data["leads"]
    state: FSMContext = data["state"]
    lang = leads.language_of(user)

    lines = [t("welcome.text", lang)]
    if settings.support_username:
        lines.extend(
            ["", t("support.line", lang, username=f"@{settings.support_username.lstrip('@')}")]
        )

    await state.set_state(FormState.choosing_action)
    await message.answer(
        "\n".join(lines),
        reply_markup=start_kb(lang),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.callback_query(F.data == "flow:start")
async def flow_start(callback: CallbackQuery, **data: Any) -> None:
    """``Boshlash`` / ``Начать`` - open (or resume) the qualification application."""
    settings: Settings = data["settings"]
    leads: LeadService = data["leads"]
    state: FSMContext = data["state"]
    lang: str = data.get("lang", settings.default_language)
    user: BotUser | None = data.get("user")

    if user is None or callback.from_user is None:  # pragma: no cover - defensive
        await callback.answer(t("err.no_active_form", lang), show_alert=True)
        return

    try:
        result = await leads.start_application(user)
    except SQLAlchemyError:
        logger.exception("could not open an application")
        await callback.answer(t("err.db", lang), show_alert=True)
        return

    if result.outcome is BeginOutcome.ALREADY_APPLIED:
        await state.set_state(FormState.choosing_action)
        kb = prompt_kb(
            [
                (t("btn.update", lang), "flow:update"),
                (t("btn.restart", lang), "flow:new"),
            ],
            columns=1,
        )
        # the lead code lets the team find the record - the score never leaves the group
        text = f"{t('info.already_applied', lang)}\n\n{t('info.lead_code', lang, code=esc(result.lead.lead_code))}"
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)
        await callback.answer()
        return

    if result.outcome is BeginOutcome.RESUMABLE_DRAFT:
        await state.set_state(FormState.choosing_action)
        kb = prompt_kb(
            [
                (t("btn.continue", lang), "flow:resume"),
                (t("btn.restart", lang), "flow:new"),
                (t("btn.cancel", lang), "flow:cancel"),
            ],
            columns=1,
        )
        try:
            await callback.message.edit_text(t("info.draft_found", lang), reply_markup=kb)
        except Exception:
            await callback.message.answer(t("info.draft_found", lang), reply_markup=kb)
        await callback.answer()
        return

    await begin_questions(callback, data, result.lead, first_step="intent")
    await callback.answer()


@router.callback_query(F.data == "flow:update")
async def flow_update(callback: CallbackQuery, **data: Any) -> None:
    """Re-open the last finished application under the same lead code."""
    leads: LeadService = data["leads"]
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)

    lead = await leads.repo.active_draft(callback.from_user.id, ttl_hours=settings.draft_ttl_hours)
    if lead is None:
        recent = await leads.repo.recent_completed(
            callback.from_user.id, within_hours=settings.recent_application_hours
        )
        if recent is None:
            await callback.answer(t("err.no_active_form", lang), show_alert=True)
            return
        lead = await leads.reset_for_update(recent)

    await begin_questions(callback, data, lead, first_step="intent")
    await callback.answer(t("info.restarted", lang))


@router.callback_query(F.data.in_({"flow:resume", "flow:new"}))
async def flow_resume_or_new(callback: CallbackQuery, **data: Any) -> None:
    leads: LeadService = data["leads"]
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)
    user: BotUser | None = data.get("user")
    if user is None:
        await callback.answer(t("err.no_active_form", lang), show_alert=True)
        return

    draft = await leads.repo.active_draft(user.telegram_user_id, ttl_hours=settings.draft_ttl_hours)
    if callback.data == "flow:new":
        if draft is not None:
            await leads.abandon(draft)
        fresh = await leads.open_new_draft(user)
        await begin_questions(callback, data, fresh, first_step="intent")
        await callback.answer()
        return

    if draft is None:
        await begin_questions(callback, data, await leads.open_new_draft(user), first_step="intent")
        await callback.answer()
        return

    step_key = await leads.resume_step(draft)
    await begin_questions(callback, data, draft, first_step=step_key)
    await leads.repo.add_event(
        FunnelEvent.RESUMED, lead_id=draft.id, telegram_user_id=user.telegram_user_id, step=step_key
    )
    await callback.answer()


@router.callback_query(F.data == "flow:cancel")
async def flow_cancel(callback: CallbackQuery, **data: Any) -> None:
    leads: LeadService = data["leads"]
    state: FSMContext = data["state"]
    lang: str = data.get("lang", "uz")
    user: BotUser | None = data.get("user")
    if user is not None:
        draft = await leads.repo.active_draft(
            user.telegram_user_id, ttl_hours=data["settings"].draft_ttl_hours
        )
        if draft is not None:
            await leads.abandon(draft)
    await state.clear()
    try:
        await callback.message.edit_text(t("info.cancelled", lang))
    except Exception:
        await callback.message.answer(t("info.cancelled", lang))
    await callback.answer()


@router.message(Command("help"), PrivateChat())
async def cmd_help(message: Message, **data: Any) -> None:
    lang: str = data.get("lang", data["settings"].default_language)
    await message.answer(t("help.text", lang))


@router.message(Command("restart"), PrivateChat())
async def cmd_restart(message: Message, **data: Any) -> None:
    """Start over: the draft is abandoned, the FSM state cleared, nothing is lost in DB."""
    leads: LeadService = data["leads"]
    state: FSMContext = data["state"]
    lang: str = data.get("lang", data["settings"].default_language)
    user: BotUser | None = data.get("user")

    if user is not None:
        draft = await leads.repo.active_draft(
            user.telegram_user_id, ttl_hours=data["settings"].draft_ttl_hours
        )
        if draft is not None:
            await leads.abandon(draft)
    await state.clear()
    if user is not None:
        await show_welcome(message, data, user)
    else:  # pragma: no cover - the middleware always fills this in private chats
        await message.answer(t("help.text", lang))


async def begin_questions(
    callback: CallbackQuery | Message, data: dict, lead, *, first_step: str
) -> None:
    """Hand the conversation over to the questionnaire engine."""
    state: FSMContext = data["state"]
    settings: Settings = data["settings"]
    await state.set_state(FormState.filling)
    await state.update_data(lead_id=lead.id, step=first_step, page=0)
    ctx = Context(
        lead=lead,
        step=STEPS[first_step],
        state=state,
        leads=data["leads"],
        repo=data["repo"],
        settings=settings,
        lang=data.get("lang", settings.default_language),
        event=callback,
    )
    await ask(ctx, first_step, edit=False)
