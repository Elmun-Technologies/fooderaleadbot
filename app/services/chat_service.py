"""Direct chat service between admins and leads."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from app.database.models import ChatDirection, ChatMessage, Lead, utcnow
from app.database.repository import LeadRepository

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, bot: Bot | None, repo: LeadRepository) -> None:
        self.bot = bot
        self.repo = repo

    async def save_inbound(
        self,
        telegram_user_id: int,
        text: str | None = None,
        *,
        lead_id: int | None = None,
        photo_file_id: str | None = None,
        document_file_id: str | None = None,
        file_name: str | None = None,
        file_type: str | None = None,
        telegram_message_id: int | None = None,
    ) -> ChatMessage:
        return await self.repo.add_chat_message(
            telegram_user_id=telegram_user_id,
            lead_id=lead_id,
            direction=ChatDirection.INBOUND.value,
            text=text,
            photo_file_id=photo_file_id,
            document_file_id=document_file_id,
            file_name=file_name,
            file_type=file_type,
            telegram_message_id=telegram_message_id,
            is_read=False,
        )

    async def send_to_user(
        self,
        telegram_user_id: int,
        text: str | None,
        *,
        lead_id: int | None = None,
        admin_user_id: int | None = None,
        admin_username: str | None = None,
        photo_file_id: str | None = None,
        document_file_id: str | None = None,
        file_name: str | None = None,
    ) -> ChatMessage | None:
        # Send via bot
        if self.bot is not None and (text or photo_file_id or document_file_id):
            try:
                if photo_file_id:
                    msg = await self.bot.send_photo(
                        telegram_user_id, photo=photo_file_id, caption=text[:1024] if text else None
                    )
                elif document_file_id:
                    msg = await self.bot.send_document(
                        telegram_user_id,
                        document=document_file_id,
                        caption=text[:1024] if text else None,
                    )
                else:
                    msg = await self.bot.send_message(
                        telegram_user_id,
                        text or "",
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
                telegram_message_id = msg.message_id
            except Exception as exc:
                logger.warning("failed to send direct message to %s: %s", telegram_user_id, exc)
                telegram_message_id = None
        else:
            telegram_message_id = None

        return await self.repo.add_chat_message(
            telegram_user_id=telegram_user_id,
            lead_id=lead_id,
            direction=ChatDirection.OUTBOUND.value,
            text=text,
            photo_file_id=photo_file_id,
            document_file_id=document_file_id,
            file_name=file_name,
            admin_user_id=admin_user_id,
            admin_username=admin_username,
            telegram_message_id=telegram_message_id,
            is_read=True,
        )

    async def get_history(self, telegram_user_id: int, limit: int = 100):
        return await self.repo.get_chat_history(telegram_user_id, limit=limit)
