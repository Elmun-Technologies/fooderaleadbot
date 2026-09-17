"""Helpers for working with raw aiogram events.

Update-level middlewares receive the whole :class:`Update`, not the inner
``Message`` / ``CallbackQuery`` - so ``event.from_user`` does not exist there.  These
helpers normalise both shapes, which keeps the middlewares short and correct.
"""

from __future__ import annotations

from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    TelegramObject,
    Update,
    User,
)

__all__ = [
    "event_callback",
    "event_chat",
    "event_message",
    "event_user",
    "inner_event",
    "is_private_chat",
]

#: order matters: the first non-empty attribute is the event we care about
_UPDATE_ATTRS: tuple[str, ...] = (
    "callback_query",
    "message",
    "edited_message",
    "business_message",
    "edited_business_message",
    "channel_post",
    "edited_channel_post",
    "inline_query",
    "chosen_inline_result",
    "shipping_query",
    "pre_checkout_query",
    "poll_answer",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
)


def inner_event(event: TelegramObject) -> TelegramObject | None:
    """Unwrap an ``Update`` into the message/callback it carries."""
    if isinstance(event, Update):
        for attribute in _UPDATE_ATTRS:
            value = getattr(event, attribute, None)
            if value is not None:
                return value
        return None
    return event


def event_user(event: TelegramObject) -> User | None:
    inner = inner_event(event)
    if inner is None:
        return None
    if isinstance(inner, Update):  # pragma: no cover - defensive
        return None
    return getattr(inner, "from_user", None)


def event_chat(event: TelegramObject) -> Chat | None:
    inner = inner_event(event)
    if inner is None:
        return None
    chat = getattr(inner, "chat", None)
    if chat is None and isinstance(inner, CallbackQuery):
        chat = getattr(inner.message, "chat", None) if inner.message else None
    return chat


def event_message(event: TelegramObject) -> Message | None:
    inner = inner_event(event)
    if isinstance(inner, Message):
        return inner
    if isinstance(inner, CallbackQuery):
        return inner.message
    return None


def event_callback(event: TelegramObject) -> CallbackQuery | None:
    inner = inner_event(event)
    return inner if isinstance(inner, CallbackQuery) else None


def is_private_chat(event: TelegramObject) -> bool:
    chat = event_chat(event)
    return bool(chat) and chat.type == "private"
