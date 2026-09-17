"""Reply keyboards (the ones Telegram requires us to build as reply KBs)."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from app.i18n import t

__all__ = ["phone_nav_action", "phone_reply_kb", "remove_reply_kb"]


def phone_reply_kb(lang: str) -> ReplyKeyboardMarkup:
    """Phone step keyboard.

    ``request_contact`` is the only way to get a Telegram-verified number; the other
    buttons keep the flow navigable (Back / Skip) and typing a number by hand is
    always allowed.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn.send_contact", lang), request_contact=True)],
            [
                KeyboardButton(text=t("btn.back", lang), request_contact=False),
                KeyboardButton(text=t("btn.skip", lang), request_contact=False),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder=t("q.phone", lang)[:64],
    )


def phone_nav_action(text: str | None, lang: str) -> str | None:
    """Map a reply-keyboard tap on the phone step to an action."""
    if not text:
        return None
    value = text.strip().lower()
    table = {
        t("btn.back", lang).strip().lower(): "back",
        t("btn.skip", lang).strip().lower(): "skip",
        t("btn.manual_phone", lang).strip().lower(): "manual",
        t("btn.send_contact", lang).strip().lower(): "manual",
    }
    return table.get(value)


def remove_reply_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove(remove_keyboard=True)
