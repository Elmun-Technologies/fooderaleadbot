"""Broadcast (rassilka) service: send messages to filtered leads with photo/file support."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile, LinkPreviewOptions

from app.database.models import Broadcast, BroadcastStatus, utcnow
from app.database.repository import LeadRepository

logger = logging.getLogger(__name__)


class BroadcastService:
    def __init__(self, bot: Bot, repo: LeadRepository) -> None:
        self.bot = bot
        self.repo = repo

    async def send_broadcast(self, broadcast_id: int) -> Broadcast | None:
        broadcast = await self.repo.get_broadcast(broadcast_id)
        if broadcast is None:
            return None

        leads = await self.repo.leads_for_broadcast(broadcast)
        total = len(leads)
        await self.repo.update_broadcast(
            broadcast.id, status=BroadcastStatus.SENDING.value, total_count=total, started_at=utcnow()
        )

        sent = 0
        failed = 0

        for lead in leads:
            try:
                await self._send_to_lead(broadcast, lead.telegram_user_id)
                sent += 1
            except TelegramRetryAfter as exc:
                logger.warning("broadcast flood wait %s", exc.retry_after)
                await asyncio.sleep(min(int(exc.retry_after), 30))
                try:
                    await self._send_to_lead(broadcast, lead.telegram_user_id)
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramForbiddenError:
                failed += 1
                logger.info("user %s blocked bot", lead.telegram_user_id)
            except Exception as exc:
                failed += 1
                logger.warning("broadcast to %s failed: %s", lead.telegram_user_id, exc)

            # small delay to avoid flood
            await asyncio.sleep(0.05)

            # update progress every 20
            if (sent + failed) % 20 == 0:
                await self.repo.update_broadcast(broadcast.id, sent_count=sent, failed_count=failed)

        final = await self.repo.update_broadcast(
            broadcast.id,
            sent_count=sent,
            failed_count=failed,
            status=BroadcastStatus.DONE.value,
            finished_at=utcnow(),
        )
        return final

    async def _send_to_lead(self, broadcast: Broadcast, chat_id: int) -> None:
        text = broadcast.text or ""
        # Priority: document > photo > text
        if broadcast.document_file_id:
            # If we have file_id from Telegram, send as document
            if broadcast.document_file_id.startswith("http"):
                # URL not supported as file_id, send text with link
                await self.bot.send_message(
                    chat_id, text, link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            else:
                await self.bot.send_document(
                    chat_id,
                    document=broadcast.document_file_id,
                    caption=text[:1024] if text else None,
                )
        elif broadcast.photo_file_id:
            if broadcast.photo_file_id.startswith("http"):
                await self.bot.send_photo(
                    chat_id, photo=broadcast.photo_file_id, caption=text[:1024] if text else None
                )
            else:
                await self.bot.send_photo(
                    chat_id, photo=broadcast.photo_file_id, caption=text[:1024] if text else None
                )
        else:
            if text:
                await self.bot.send_message(
                    chat_id, text, link_preview_options=LinkPreviewOptions(is_disabled=True)
                )

    async def preview_targets(self, broadcast: Broadcast) -> int:
        leads = await self.repo.leads_for_broadcast(broadcast)
        return len(leads)
