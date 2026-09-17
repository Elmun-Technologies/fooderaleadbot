"""Request context: DB session, repository, services, user and language."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.config import Settings
from app.database.repository import LeadRepository
from app.database.session import Database
from app.services.lead_service import LeadService
from app.services.notification import LeadNotifier
from app.utils.events import event_user, is_private_chat

__all__ = ["DatabaseMiddleware", "UserContextMiddleware"]

logger = logging.getLogger(__name__)

Handler = Callable[[Any, dict[str, Any]], Awaitable[Any]]


class DatabaseMiddleware(BaseMiddleware):
    """Attach an ``AsyncSession``, a :class:`LeadRepository` and services to every update.

    The session lives exactly as long as the handler: it is closed (and rolled back
    on error) even if a handler raises, so a broken query can never leak a
    connection or leave a half-written transaction.
    """

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.database.session() as session:
            data["session"] = session
            repo = LeadRepository(session)
            data["repo"] = repo
            data["settings"] = self.settings
            notifier = LeadNotifier(data.get("bot"), self.settings)
            data["notifier"] = notifier
            data["leads"] = LeadService(repo, self.settings, notifier)
            return await handler(event, data)


class UserContextMiddleware(BaseMiddleware):
    """Resolve the language of the acting Telegram user (private chats only)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        from_user = event_user(event)
        if from_user is not None:
            data["user_id"] = from_user.id
            language = self.settings.default_language
            repo: LeadRepository | None = data.get("repo")
            if repo is not None and is_private_chat(event):
                try:
                    user = await repo.get_user(from_user.id)
                except Exception:  # pragma: no cover - DB hiccup must not break updates
                    logger.exception("could not load user profile")
                    user = None
                if user is not None and user.language:
                    language = user.language
                data["user"] = user
                data["telegram_language"] = from_user.language_code
            data["lang"] = language
        return await handler(event, data)
