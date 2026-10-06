"""The questionnaire engine shared by the exhibitor and visitor funnels.

One question per screen, inline buttons wherever possible, Back/Skip navigation and a
progress counter.  Steps are declared in :mod:`app.flow`; this module only knows how to
*render* a step and how to *apply* an answer, so adding a question never means adding
a handler.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database.models import Lead
from app.database.repository import LeadRepository
from app.flow import (
    REGION_STEPS,
    STEPS,
    Step,
    StepError,
    StepKind,
    next_step,
    prev_step,
    progress_of,
    validate_inline,
    validate_text,
)
from app.i18n import t
from app.keyboards.inline import category_kb, choice_value, question_kb, single_choice_kb
from app.keyboards.reply import phone_nav_action, phone_reply_kb, remove_reply_kb
from app.options import Region
from app.services.lead_service import FinalizeResult, LeadService
from app.services.parsing import parse_contact_line
from app.utils.phone import normalize_phone
from app.utils.text import clean_text, esc

__all__ = [
    "Context",
    "Render",
    "advance",
    "apply_inline_answer",
    "apply_phone",
    "apply_text_answer",
    "ask",
    "build_question",
    "finish",
    "go_back",
    "handle_category_page",
    "handle_choice",
    "handle_contact_share",
    "handle_nav",
    "handle_text",
    "require_context",
    "skip",
]

logger = logging.getLogger(__name__)

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@dataclass
class Context:
    """Everything a step handler needs for the current user turn."""

    lead: Lead
    step: Step
    state: FSMContext
    leads: LeadService
    repo: LeadRepository
    settings: Settings
    lang: str
    event: Message | CallbackQuery

    @property
    def message(self) -> Message | None:
        return self.event.message if isinstance(self.event, CallbackQuery) else self.event

    async def answer(self, text: str, *, show_alert: bool = False) -> None:
        """Toast for callback presses, plain message for text turns."""
        if isinstance(self.event, CallbackQuery):
            try:
                await self.event.answer(text, show_alert=show_alert)
                return
            except TelegramBadRequest:  # pragma: no cover - stale query id
                pass
        target = self.message
        if target is not None:
            try:
                await target.answer(text, link_preview_options=_NO_PREVIEW)
            except TelegramBadRequest:  # pragma: no cover - chat disappeared
                logger.debug("could not answer user %s", self.lead.telegram_user_id)


# --------------------------------------------------------------------------- render
@dataclass(frozen=True)
class Render:
    text: str
    keyboard: InlineKeyboardMarkup | None = None
    reply_keyboard: ReplyKeyboardMarkup | None = None


def _current_value(lead: Lead, step: Step) -> str | None:
    """Previously stored answer, so "Back" shows what the user picked before."""
    if not step.fields:
        return None
    value = getattr(lead, step.fields[0], None)
    return str(value) if value else None


def build_question(
    lead: Lead,
    step_key: str,
    lang: str,
    *,
    page: int = 0,
    error: str | None = None,
) -> Render:
    """Render a single question (text + keyboard).  Pure, so it is unit-testable."""
    step = STEPS[step_key]
    index, total = progress_of(step_key, lead.field_values())
    current = _current_value(lead, step)

    lines: list[str] = [
        t("progress", lang, step=index, total=total),
        "",
        t(step.question_key, lang),
    ]

    if step.hint_key:
        lines.append(f"<i>{esc(t(step.hint_key, lang))}</i>")
    if current and step.kind in (StepKind.TEXT, StepKind.PHONE):
        lines.append(f"<i>{esc(t('info.current', lang, value=current))}</i>")

    keyboard: InlineKeyboardMarkup | None = None
    reply_keyboard: ReplyKeyboardMarkup | None = None

    if step.kind is StepKind.INLINE:
        keyboard = single_choice_kb(
            str(step.group),
            lang,
            step.key,
            columns=step.columns,
            back=step.allow_back,
            skip=step.optional,
            current=current,
            only=step.options,
        )
    elif step.kind is StepKind.CATEGORY:
        keyboard, _, _ = category_kb(lang, page=page, current=current, back=step.allow_back)
    elif step.kind is StepKind.PHONE:
        reply_keyboard = phone_reply_kb(lang)
    else:  # TEXT
        keyboard = question_kb(lang, back=step.allow_back, skip=step.optional)

    if error:
        lines.extend(["", f"⚠️ {esc(error)}"])

    return Render(text="\n".join(lines), keyboard=keyboard, reply_keyboard=reply_keyboard)


# ---------------------------------------------------------------------------- apply
def apply_inline_answer(step: Step, value: str, lead: Lead) -> dict[str, Any]:
    """Translate an inline choice into lead fields (validated against the option group)."""
    if step.group:
        validate_inline(step.group, value)

    if step.key == "intent":
        return {"intent": value}
    if step.key in REGION_STEPS:
        # switching away from "outside Uzbekistan" must not keep a stale country
        keep_country = value == Region.FOREIGN.value
        return {"region": value, "country": lead.country if keep_country else None}
    field = step.fields[0]
    return {field: value}


def apply_text_answer(step: Step, text: str, lead: Lead | None = None) -> dict[str, Any]:
    """Validate + map free-text answers (company name, country, contact line, phone)."""
    if step.kind is StepKind.PHONE:
        return apply_phone(text)

    cleaned = validate_text(step, text)
    if step.key == "contact":
        name, position = parse_contact_line(cleaned)
        if not name:
            raise StepError(step.error_key, min=step.min_len or 2)
        return {"contact_name": name, "position": position}
    if step.key == "visitor_name":
        return {"contact_name": clean_text(cleaned, max_len=120)}
    field = step.fields[0] if step.fields else "company_name"
    return {field: cleaned}


def apply_phone(raw: str | None) -> dict[str, Any]:
    phone = normalize_phone(raw)
    if not phone.valid:
        raise StepError("err.phone_format")
    return {"phone": phone.number}


# ------------------------------------------------------------------------------ io
async def require_context(
    event: Message | CallbackQuery,
    data: dict[str, Any],
    *,
    allowed_steps: frozenset[str] | None = None,
) -> Context | None:
    """Load FSM state + draft lead and resolve the step to show.

    Returns ``None`` (after telling the user what happened) when the conversation has
    no usable context - e.g. after a bot restart with an empty FSM storage, or when a
    manager taps a button on an old lead card.
    """
    state: FSMContext = data["state"]
    leads: LeadService = data["leads"]
    repo: LeadRepository = data["repo"]
    settings: Settings = data["settings"]
    lang: str = data.get("lang", settings.default_language)

    fsm = await state.get_data()
    lead_id = fsm.get("lead_id")
    lead = await repo.get_lead(int(lead_id)) if lead_id else None
    if lead is None:
        user = data.get("user")
        if user is not None:
            lead = await repo.active_draft(
                user.telegram_user_id, ttl_hours=settings.draft_ttl_hours
            )

    if lead is None:
        await _notify(event, t("err.no_active_form", lang), lang=lang)
        await state.clear()
        return None

    step_key = str(fsm.get("step") or "")
    if step_key not in STEPS:
        step_key = await leads.resume_step(lead)
    if allowed_steps is not None and step_key not in allowed_steps:
        return None  # this step belongs to the other funnel's router

    return Context(
        lead=lead,
        step=STEPS[step_key],
        state=state,
        leads=leads,
        repo=repo,
        settings=settings,
        lang=lang,
        event=event,
    )


async def _notify(event: Message | CallbackQuery, text: str, *, lang: str = "uz") -> None:
    if isinstance(event, CallbackQuery):
        try:
            await event.answer(text)
            return
        except TelegramBadRequest:  # pragma: no cover
            return
    try:
        await event.answer(text, link_preview_options=_NO_PREVIEW)
    except TelegramBadRequest:  # pragma: no cover
        logger.debug("could not notify user")


async def ask(
    ctx: Context,
    step_key: str,
    *,
    page: int = 0,
    error: str | None = None,
    edit: bool = True,
) -> None:
    """Show a question: edit the existing message when possible, else send a new one."""
    render = build_question(ctx.lead, step_key, ctx.lang, page=page, error=error)
    await ctx.state.update_data(step=step_key, page=page, lead_id=ctx.lead.id)

    target = ctx.message
    if target is None:  # pragma: no cover - defensive
        return

    markup = render.reply_keyboard or render.keyboard
    if isinstance(ctx.event, CallbackQuery) and edit and render.reply_keyboard is None:
        try:
            await target.edit_text(
                render.text, reply_markup=markup, link_preview_options=_NO_PREVIEW
            )
            await ctx.event.answer()
            return
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                logger.debug("could not edit question: %s", exc)
        with suppress(TelegramBadRequest):  # the question may already be answered
            await ctx.event.answer()

    await target.answer(render.text, reply_markup=markup, link_preview_options=_NO_PREVIEW)


# --------------------------------------------------------------------- transitions
async def advance(
    ctx: Context, values: dict[str, Any], *, event_name: str | None = None
) -> FinalizeResult | None:
    """Persist the answer, then show the next question or finish the funnel."""
    try:
        updated = await ctx.leads.save_answer(ctx.lead, ctx.step.key, values, event=event_name)
    except SQLAlchemyError:
        logger.exception("failed to store the answer of step %s", ctx.step.key)
        await ctx.answer(t("err.db", ctx.lang), show_alert=True)
        return None

    ctx.lead = updated
    following = updated.current_step or next_step(ctx.step.key, updated.field_values())
    if following is None:
        return await finish(ctx)
    await ask(ctx, following)
    return None


async def skip(ctx: Context) -> None:
    """Optional steps may be skipped - the lead is still a lead."""
    await ctx.leads.mark_skipped(ctx.lead, ctx.step.key)
    following = next_step(ctx.step.key, ctx.lead.field_values())
    if following is None:
        await finish(ctx)
        return
    await ask(ctx, following)


async def go_back(ctx: Context) -> None:
    previous = prev_step(ctx.step.key, ctx.lead.field_values())
    if previous is None:
        await ctx.answer(t("info.first_question", ctx.lang))
        return
    await ask(ctx, previous)


async def finish(ctx: Context) -> FinalizeResult:
    """Score, classify, notify the sales team and thank the user."""
    result = await ctx.leads.finalize(ctx.lead)
    await ctx.state.clear()

    lines = [t(result.success_key, ctx.lang)]
    support = ctx.settings.support_username
    if support:
        lines.extend(["", t("support.line", ctx.lang, username=f"@{support.lstrip('@')}")])

    if isinstance(ctx.event, CallbackQuery):
        with suppress(TelegramBadRequest):
            await ctx.event.answer()

    text = "\n".join(lines)
    target = ctx.message
    if target is not None:
        try:
            await target.answer(
                text, reply_markup=remove_reply_kb(), link_preview_options=_NO_PREVIEW
            )
        except TelegramBadRequest:  # pragma: no cover - user left the chat
            logger.warning("could not deliver the completion message for %s", ctx.lead.lead_code)
    return result


# ------------------------------------------------------------------ answer dispatch
async def handle_choice(callback: CallbackQuery, data: dict[str, Any]) -> None:
    """Generic ``q:<step>:<value>`` handler - every inline question of both funnels."""
    ctx = await require_context(callback, data)
    if ctx is None:
        await _notify(
            callback, t("err.stale_callback", data.get("lang", "uz")), lang=data.get("lang", "uz")
        )
        return

    parsed = choice_value(str(callback.data or ""))
    if parsed is None:
        await ctx.answer(t("err.stale_callback", ctx.lang))
        return

    step_key, value = parsed
    if step_key != ctx.step.key:
        # pressed a button of an already answered question - show the current one
        await ctx.answer(t("err.stale_callback", ctx.lang), show_alert=True)
        await ask(ctx, ctx.step.key)
        return

    try:
        values = apply_inline_answer(ctx.step, value, ctx.lead)
    except StepError as exc:
        await ctx.answer(t(exc.message_key, ctx.lang), show_alert=True)
        return

    await advance(ctx, values)


async def handle_category_page(callback: CallbackQuery, data: dict[str, Any]) -> None:
    """``cat:page:<n>`` - paginate the 16 FOODERA directions instead of a huge keyboard."""
    ctx = await require_context(callback, data)
    if ctx is None or ctx.step.kind is not StepKind.CATEGORY:
        await _notify(
            callback, t("err.stale_callback", data.get("lang", "uz")), lang=data.get("lang", "uz")
        )
        return

    parts = str(callback.data or "").split(":")
    page = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else 0
    render = build_question(ctx.lead, ctx.step.key, ctx.lang, page=page)
    await ctx.state.update_data(page=page)
    try:
        if callback.message is not None:
            await callback.message.edit_text(
                render.text, reply_markup=render.keyboard, link_preview_options=_NO_PREVIEW
            )
        await callback.answer()
    except TelegramBadRequest as exc:
        logger.debug("category page edit failed: %s", exc)
        with suppress(TelegramBadRequest):
            await callback.answer()


async def handle_text(message: Message, data: dict[str, Any]) -> None:
    """Free-text answers: company name, contact line, country, phone."""
    ctx = await require_context(message, data)
    if ctx is None:
        return

    step = ctx.step
    text = message.text or ""

    if step.kind is StepKind.PHONE:
        action = phone_nav_action(text, ctx.lang)
        if action == "back":
            await go_back(ctx)
            return
        if action == "skip":
            await skip(ctx)
            return

    if step.kind in (StepKind.INLINE, StepKind.CATEGORY):
        await ask(ctx, step.key, error=t("err.use_buttons", ctx.lang))
        return

    try:
        values = apply_text_answer(step, text, ctx.lead)
    except StepError as exc:
        await ask(ctx, step.key, error=t(exc.message_key, ctx.lang, **exc.context))
        return

    await advance(ctx, values)


async def handle_contact_share(message: Message, data: dict[str, Any]) -> None:
    """``📱 Send my phone number`` - the only way to get a Telegram-verified number."""
    ctx = await require_context(message, data)
    if ctx is None:
        return
    if ctx.step.kind is not StepKind.PHONE:
        await message.answer(t("err.stale_callback", ctx.lang), link_preview_options=_NO_PREVIEW)
        return

    contact = message.contact
    if contact is None or not contact.phone_number:
        await ask(ctx, ctx.step.key, error=t("err.phone_format", ctx.lang))
        return
    if contact.user_id and message.from_user and contact.user_id != message.from_user.id:
        await ask(ctx, ctx.step.key, error=t("err.phone_foreign", ctx.lang))
        return

    try:
        values = apply_phone(contact.phone_number)
    except StepError as exc:
        await ask(ctx, ctx.step.key, error=t(exc.message_key, ctx.lang))
        return
    await advance(ctx, values)


async def handle_nav(callback: CallbackQuery, data: dict[str, Any]) -> None:
    """``nav:back`` / ``nav:skip`` / ``nav:manual``."""
    ctx = await require_context(callback, data)
    if ctx is None:
        await _notify(
            callback, t("err.stale_callback", data.get("lang", "uz")), lang=data.get("lang", "uz")
        )
        return

    action = str(callback.data or "").split(":", 1)[-1]
    if action == "back":
        await go_back(ctx)
    elif action == "skip":
        if not ctx.step.optional:
            await ctx.answer(t("info.field_required", ctx.lang))
            return
        await skip(ctx)
    elif action == "manual":
        await ask(ctx, ctx.step.key, error=t("hint.phone", ctx.lang))
    else:  # pragma: no cover
        await ctx.answer(t("err.stale_callback", ctx.lang))
    with suppress(TelegramBadRequest):
        await callback.answer()
