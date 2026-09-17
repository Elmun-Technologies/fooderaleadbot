"""Language selection (Uzbek Latin / Russian).

Asked once, on first launch, then persisted on the user profile.  Changing the
language re-renders the current question, so a user never has to restart the funnel.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import Settings
from app.database.models import BotUser, FunnelEvent
from app.flow import STEPS
from app.handlers.engine import Context, ask
from app.i18n import normalize_language, t
from app.keyboards.inline import language_kb
from app.states import FormState

__all__ = ["ask_language", "router"]

logger = logging.getLogger(__name__)

router = Router(name="language")


async def ask_language(message: Message, data: dict, user: BotUser | None = None) -> None:
    """First-launch question. Two buttons, nothing else."""
    settings: Settings = data["settings"]
    state: FSMContext = data["state"]
    await state.set_state(FormState.choosing_language)
    await message.answer(
        t("lang.choose", user.language if user and user.language else settings.default_language),
        reply_markup=language_kb(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery, **data: Any) -> None:
    settings: Settings = data["settings"]
    state: FSMContext = data["state"]
    leads = data["leads"]
    user: BotUser | None = data.get("user")
    raw = str(callback.data or "")
    code = normalize_language(raw.split(":", 1)[-1])

    if user is None and callback.from_user is not None:
        user = await leads.ensure_user(
            callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
        )
    if user is None:  # pragma: no cover - defensive
        await callback.answer(t("err.db", code), show_alert=True)
        return

    user = await leads.set_language(user, code)
    await leads.repo.add_event(
        FunnelEvent.LANGUAGE_SELECTED,
        telegram_user_id=user.telegram_user_id,
        data={"language": code},
    )

    state_data = await state.get_data()
    lang = normalize_language(user.language)

    if state_data.get("step") and state_data.get("lead_id"):
        # mid-questionnaire: re-render the current question in the new language
        lead = await data["repo"].get_lead(int(state_data["lead_id"]))
        if lead is not None:
            step_key = str(state_data.get("step") or "intent")
            ctx = Context(
                lead=lead,
                step=STEPS.get(step_key, STEPS["intent"]),
                state=state,
                leads=leads,
                repo=data["repo"],
                settings=settings,
                lang=lang,
                event=callback,
            )
            data["lang"] = lang
            await state.update_data(step=step_key)
            await ask(ctx, step_key)
            await callback.answer(t("info.lang_saved", lang))
            return

    await state.set_state(FormState.choosing_action)
    if callback.message is not None:
        # local import: start.py imports ask_language() from this module
        from app.handlers.start import show_welcome

        with suppress(Exception):  # cosmetic only: the old prompt may be un-deletable
            await callback.message.delete()
        await show_welcome(callback.message, data, user)
    await callback.answer(t("info.lang_saved", lang))
