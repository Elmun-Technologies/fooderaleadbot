"""Cheap, dependency-free flood control.

Telegram Ads traffic arrives in bursts; we do not want a single user (or a bot
farm hammering one account) to hammer the database or the sales group.  The
limiter is per-user and in-process, which is exactly what a single bot instance
needs - put Redis in front if you ever scale to several instances.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from app.config import Settings
from app.i18n import t
from app.utils.events import event_message, event_user

__all__ = ["ThrottlingMiddleware"]

logger = logging.getLogger(__name__)

Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


class ThrottlingMiddleware(BaseMiddleware):
    """Sliding-window rate limiter: ``limit`` actions per 60 seconds per user."""

    def __init__(self, limit: int | None = None, *, per_seconds: float = 60.0) -> None:
        self.per_seconds = per_seconds
        self.limit = int(limit) if limit else None
        self._events: dict[int, deque[float]] = defaultdict(deque)
        self._warned: dict[int, float] = {}

    def _resolve_limit(self, settings: Settings | None) -> int:
        if self.limit is not None:
            return self.limit
        value = getattr(settings, "rate_limit_per_minute", 30) or 30
        return max(5, int(value))

    def allow(self, user_id: int, limit: int) -> bool:
        now = time.monotonic()
        bucket = self._events[user_id]
        while bucket and now - bucket[0] > self.per_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        if len(bucket) == 1 and len(self._events) > 10_000:  # pragma: no cover - hygiene
            self._events.clear()
            self._warned.clear()
        return True

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        settings: Settings | None = data.get("settings")
        from_user = event_user(event)
        if from_user is None or (settings is not None and from_user.id in settings.admin_user_ids):
            return await handler(event, data)

        limit = self._resolve_limit(settings)
        if self.allow(from_user.id, limit):
            return await handler(event, data)

        logger.warning("rate limit exceeded for user %s (limit %s/min)", from_user.id, limit)
        language = data.get("lang", "uz")
        if isinstance(event, CallbackQuery):
            with suppress(Exception):  # a stale query cannot be answered, that is fine
                await event.answer(t("err.rate_limited", language), show_alert=True)
            return None
        now = time.monotonic()
        if now - self._warned.get(from_user.id, 0.0) > self.per_seconds:
            self._warned[from_user.id] = now
            message = event_message(event) or event
            answer = getattr(message, "answer", None)
            if callable(answer):
                with suppress(Exception):  # the user may have blocked the bot
                    await answer(t("err.rate_limited", language))
        return None
