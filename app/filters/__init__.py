"""Custom filters."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import Settings

__all__ = ["AdminFilter", "IsOwnerOrAdmin", "PrivateChat"]


class AdminFilter(BaseFilter):
    """Only users listed in ``ADMIN_USER_IDS`` (numeric ids, never usernames)."""

    async def check(self, user_id: int | None, settings: Settings | None) -> bool:
        if user_id is None or settings is None:
            return False
        return user_id in settings.admin_user_ids


class IsOwnerOrAdmin(AdminFilter):
    """Admin commands *and* lead-card management inside the sales group."""

    def __init__(self, *, allow_group_managers: bool | None = None) -> None:
        self._allow_group_managers = allow_group_managers

    async def __call__(
        self,
        event: Message | CallbackQuery,
        settings: Settings | None = None,
    ) -> bool:
        from_user = getattr(event, "from_user", None)
        if from_user is None or settings is None:
            return False
        if from_user.id in settings.admin_user_ids:
            return True
        allow_group = (
            settings.allow_group_managers
            if self._allow_group_managers is None
            else self._allow_group_managers
        )
        if not allow_group or not settings.sales_group_id:
            return False
        chat = getattr(event, "message", event)
        chat = getattr(chat, "chat", None)
        return bool(chat) and chat.id == settings.sales_group_id


class PrivateChat(BaseFilter):
    """Reject anything that is not a private dialog (bots in groups, channels...)."""

    async def __call__(self, message: Message) -> bool:
        return message.chat.type == "private"
