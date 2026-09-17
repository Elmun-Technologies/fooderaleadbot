"""Marketing follow-up service - proactive inside-bot marketing."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import LinkPreviewOptions

from app.database.models import (
    BotUser,
    FollowUpLog,
    FollowUpStatus,
    FollowUpTemplate,
    FollowUpTrigger,
    Lead,
    utcnow,
)
from app.database.repository import LeadRepository

logger = logging.getLogger(__name__)


DEFAULT_TEMPLATES = [
    # Draft abandoned - UZ
    {
        "name": "Draft 2h - UZ",
        "trigger": FollowUpTrigger.DRAFT_ABANDONED.value,
        "delay_hours": 2,
        "language": "uz",
        "text": (
            "👋 Salom! Siz FOODERA EXPO 2026 uchun arizani to'ldirishni boshladingiz, lekin tugatmadigingiz.\n\n"
            "Davom etish uchun /start bosing - atigi 2 daqiqa!\n\n"
            "📅 20–22 oktabr 2026\n📍 SOF EXPO, Samarqand"
        ),
        "is_active": True,
        "priority": 10,
    },
    {
        "name": "Draft 24h - UZ",
        "trigger": FollowUpTrigger.DRAFT_ABANDONED.value,
        "delay_hours": 24,
        "language": "uz",
        "text": (
            "⏰ Eslatma: sizning FOODERA EXPO arizangiz hali tugallanmagan.\n\n"
            "Joylar cheklangan! Hoziroq yakunlang: /start\n\n"
            "Savollar bo'lsa, shu yerda yozing - menejerimiz javob beradi."
        ),
        "is_active": True,
        "priority": 9,
    },
    # Draft abandoned - RU
    {
        "name": "Draft 2h - RU",
        "trigger": FollowUpTrigger.DRAFT_ABANDONED.value,
        "delay_hours": 2,
        "language": "ru",
        "text": (
            "👋 Здравствуйте! Вы начали заполнять заявку на FOODERA EXPO 2026, но не закончили.\n\n"
            "Продолжите: /start - всего 2 минуты!\n\n"
            "📅 20–22 октября 2026\n📍 SOF EXPO, Самарканд"
        ),
        "is_active": True,
        "priority": 10,
    },
    {
        "name": "Draft 24h - RU",
        "trigger": FollowUpTrigger.DRAFT_ABANDONED.value,
        "delay_hours": 24,
        "language": "ru",
        "text": (
            "⏰ Напоминание: ваша заявка на FOODERA EXPO еще не завершена.\n\n"
            "Места ограничены! Завершите сейчас: /start\n\n"
            "Если есть вопросы - напишите здесь."
        ),
        "is_active": True,
        "priority": 9,
    },
    # Started but not completed - UZ
    {
        "name": "Started no lead 1h - UZ",
        "trigger": FollowUpTrigger.STARTED_NOT_COMPLETED.value,
        "delay_hours": 1,
        "language": "uz",
        "text": (
            "👋 Assalomu alaykum! FOODERA EXPO ga qiziqish bildirganingiz uchun rahmat.\n\n"
            "Arizani to'ldirish 2 daqiqa, stendlar va narxlar haqida to'liq ma'lumot olasiz: /start\n\n"
            "🤝 100+ kompaniya allaqachon ro'yxatdan o'tgan!"
        ),
        "is_active": True,
        "priority": 8,
    },
    {
        "name": "Started no lead 1h - RU",
        "trigger": FollowUpTrigger.STARTED_NOT_COMPLETED.value,
        "delay_hours": 1,
        "language": "ru",
        "text": (
            "👋 Здравствуйте! Спасибо за интерес к FOODERA EXPO.\n\n"
            "Заполнение заявки займет 2 минуты, вы получите полную информацию о стендах и ценах: /start\n\n"
            "🤝 Уже 100+ компаний зарегистрировались!"
        ),
        "is_active": True,
        "priority": 8,
    },
    # Completed exhibitor - UZ
    {
        "name": "Exhibitor completed 10m - UZ",
        "trigger": FollowUpTrigger.COMPLETED_EXHIBITOR.value,
        "delay_hours": 0,
        "language": "uz",
        "text": (
            "🎉 Rahmat! Arizangiz qabul qilindi va menejerlarimizga yuborildi.\n\n"
            "Keyingi qadamlar:\n"
            "1️⃣ Menejer 24 soat ichida bog'lanadi\n"
            "2️⃣ Sizga mos stend variantlarini ko'rsatadi\n"
            "3️⃣ Shartnoma va to'lov\n\n"
            "Savollaringiz bo'lsa shu yerda yozing - tez javob beramiz!\n\n"
            "📅 20–22 oktabr 2026 - SOF EXPO, Samarqand da ko'rishguncha!"
        ),
        "is_active": True,
        "priority": 10,
    },
    {
        "name": "Exhibitor completed 1d - UZ",
        "trigger": FollowUpTrigger.COMPLETED_EXHIBITOR.value,
        "delay_hours": 24,
        "language": "uz",
        "text": (
            "📅 FOODERA EXPO 2026 yaqinlashmoqda!\n\n"
            "Stend tanlashda yordam kerakmi? Menejer bilan gaplashing.\n\n"
            "🔥 HOT leadlar uchun maxsus joylar ajratilgan - ulgurib qoling!\n\n"
            "Savollar: shu yerda yozing yoki /help"
        ),
        "is_active": True,
        "priority": 5,
    },
    {
        "name": "Exhibitor completed 10m - RU",
        "trigger": FollowUpTrigger.COMPLETED_EXHIBITOR.value,
        "delay_hours": 0,
        "language": "ru",
        "text": (
            "🎉 Спасибо! Ваша заявка принята и отправлена менеджерам.\n\n"
            "Следующие шаги:\n"
            "1️⃣ Менеджер свяжется в течение 24 часов\n"
            "2️⃣ Покажет подходящие варианты стендов\n"
            "3️⃣ Договор и оплата\n\n"
            "Если есть вопросы - пишите здесь!\n\n"
            "📅 До встречи 20–22 октября 2026 - SOF EXPO, Самарканд!"
        ),
        "is_active": True,
        "priority": 10,
    },
    # Visitor - UZ
    {
        "name": "Visitor 10m - UZ",
        "trigger": FollowUpTrigger.COMPLETED_VISITOR.value,
        "delay_hours": 0,
        "language": "uz",
        "text": (
            "👤 Mehmon sifatida ro'yxatdan o'tganingiz uchun rahmat!\n\n"
            "🎟 Sizni FOODERA EXPO 2026 da kutamiz:\n"
            "📅 20–22 oktabr 2026\n"
            "📍 SOF EXPO, Samarqand\n\n"
            "Dastur, ishtirokchilar ro'yxati va B2B uchrashuvlar tez orada e'lon qilinadi.\n"
            "Yangiliklarni o'tkazib yubormaslik uchun kanalimizga obuna bo'ling!"
        ),
        "is_active": True,
        "priority": 10,
    },
    {
        "name": "Visitor 3d - UZ",
        "trigger": FollowUpTrigger.COMPLETED_VISITOR.value,
        "delay_hours": 72,
        "language": "uz",
        "text": (
            "🎉 FOODERA EXPO da sizni nimalar kutmoqda?\n\n"
            "✅ 100+ ishlab chiqaruvchi\n"
            "✅ B2B muzokaralar\n"
            "✅ Master-klasslar va taqdimotlar\n"
            "✅ Yangi mahsulotlar degustatsiyasi\n\n"
            "Do'stlaringizni ham taklif qiling! /start"
        ),
        "is_active": True,
        "priority": 5,
    },
    {
        "name": "Visitor 10m - RU",
        "trigger": FollowUpTrigger.COMPLETED_VISITOR.value,
        "delay_hours": 0,
        "language": "ru",
        "text": (
            "👤 Спасибо за регистрацию как гость!\n\n"
            "🎟 Ждем вас на FOODERA EXPO 2026:\n"
            "📅 20–22 октября 2026\n"
            "📍 SOF EXPO, Самарканд\n\n"
            "Программа, список участников и B2B встречи скоро будут объявлены."
        ),
        "is_active": True,
        "priority": 10,
    },
    # HOT lead follow-up
    {
        "name": "HOT 1h - UZ",
        "trigger": FollowUpTrigger.HOT_LEAD.value,
        "delay_hours": 1,
        "language": "uz",
        "text": (
            "🔥 Siz HOT lead sifatida belgilandingiz!\n\n"
            "Bu degani kompaniyangiz FOODERA uchun ideal ishtirokchi.\n"
            "Menejerimiz siz bilan ustuvor tartibda bog'lanadi.\n\n"
            "Shoshilinch savollar bo'lsa shu yerda yozing!"
        ),
        "is_active": True,
        "priority": 9,
    },
    {
        "name": "HOT 1h - RU",
        "trigger": FollowUpTrigger.HOT_LEAD.value,
        "delay_hours": 1,
        "language": "ru",
        "text": (
            "🔥 Вы отмечены как HOT лид!\n\n"
            "Ваша компания - идеальный участник для FOODERA.\n"
            "Менеджер свяжется с вами в приоритетном порядке.\n\n"
            "Если есть срочные вопросы - пишите здесь!"
        ),
        "is_active": True,
        "priority": 9,
    },
    # STATUS NEW after 24h
    {
        "name": "Status NEW 24h - UZ",
        "trigger": FollowUpTrigger.STATUS_NEW.value,
        "delay_hours": 24,
        "language": "uz",
        "text": (
            "📞 Sizning arizangiz hali NEW holatida.\n\n"
            "Menejerimiz siz bilan bog'lanishga harakat qildi, lekin javob bo'lmadi.\n"
            "Qachon gaplasha olamiz? Shu yerda vaqtni yozing.\n\n"
            "Yoki telefon qiling: +998 XX XXX XX XX"
        ),
        "is_active": True,
        "priority": 6,
    },
    {
        "name": "Status NEW 24h - RU",
        "trigger": FollowUpTrigger.STATUS_NEW.value,
        "delay_hours": 24,
        "language": "ru",
        "text": (
            "📞 Ваша заявка все еще в статусе NEW.\n\n"
            "Менеджер пытался связаться, но не дозвонился.\n"
            "Когда вам удобно поговорить? Напишите время здесь."
        ),
        "is_active": True,
        "priority": 6,
    },
]


class FollowUpService:
    def __init__(self, bot: Bot | None, repo):
        self.bot = bot
        self.repo = repo

    async def ensure_default_templates(self):
        existing = await self.repo.list_followup_templates()
        if existing:
            return
        for data in DEFAULT_TEMPLATES:
            await self.repo.create_followup_template(**data)
        logger = logging.getLogger(__name__)
        logger.info("created %s default follow-up templates", len(DEFAULT_TEMPLATES))

    async def schedule_due_followups(self) -> int:
        """Find users matching active templates and schedule logs."""
        templates = await self.repo.list_followup_templates(only_active=True)
        scheduled = 0
        for template in templates:
            try:
                targets = await self.repo.find_users_for_followup(template)
                for target in targets:
                    if isinstance(target, BotUser):
                        tg_id = target.telegram_user_id
                        lead_id = None
                        bot_user_id = target.id
                    else:  # Lead
                        tg_id = target.telegram_user_id
                        lead_id = target.id
                        bot_user_id = target.bot_user_id

                    # Skip if already has log
                    if await self.repo.has_followup_log(tg_id, template.id):
                        continue

                    await self.repo.schedule_followup_for_user(
                        template, telegram_user_id=tg_id, lead_id=lead_id, bot_user_id=bot_user_id
                    )
                    scheduled += 1
            except Exception as exc:
                logging.getLogger(__name__).warning("failed to schedule for template %s: %s", template.id, exc)
        return scheduled

    async def send_due_followups(self, *, limit: int = 100) -> tuple[int, int]:
        """Send pending follow-ups that are due."""
        logs = await self.repo.get_due_followups(limit=limit)
        sent = 0
        failed = 0

        for log in logs:
            template = await self.repo.get_followup_template(log.template_id)
            if not template or not template.is_active:
                continue

            try:
                await self._send_followup(log, template)
                # Update log
                await self.repo.session.execute(
                    # use direct update to avoid ORM reload issues
                    __import__("sqlalchemy").update(FollowUpLog)
                    .where(FollowUpLog.id == log.id)
                    .values(status=FollowUpStatus.SENT.value, sent_at=utcnow())
                )
                await self.repo.session.commit()
                # Increment template counter
                await self.repo.session.execute(
                    __import__("sqlalchemy").update(FollowUpTemplate)
                    .where(FollowUpTemplate.id == template.id)
                    .values(total_sent=FollowUpTemplate.total_sent + 1)
                )
                await self.repo.session.commit()
                sent += 1
                await asyncio.sleep(0.1)  # avoid flood
            except TelegramRetryAfter as exc:
                await asyncio.sleep(min(int(exc.retry_after), 30))
                failed += 1
            except TelegramForbiddenError:
                # User blocked bot
                await self.repo.session.execute(
                    __import__("sqlalchemy").update(FollowUpLog)
                    .where(FollowUpLog.id == log.id)
                    .values(status=FollowUpStatus.FAILED.value, error="blocked")
                )
                await self.repo.session.commit()
                failed += 1
            except Exception as exc:
                await self.repo.session.execute(
                    __import__("sqlalchemy").update(FollowUpLog)
                    .where(FollowUpLog.id == log.id)
                    .values(status=FollowUpStatus.FAILED.value, error=str(exc)[:200])
                )
                await self.repo.session.commit()
                failed += 1
                logging.getLogger(__name__).warning("follow-up %s failed: %s", log.id, exc)

        return sent, failed

    async def _send_followup(self, log: FollowUpLog, template: FollowUpTemplate):
        if not self.bot:
            raise RuntimeError("bot not configured")

        chat_id = log.telegram_user_id
        text = template.text

        if template.photo_file_id:
            await self.bot.send_photo(chat_id, photo=template.photo_file_id, caption=text[:1024] if text else None)
        elif template.document_file_id:
            await self.bot.send_document(chat_id, document=template.document_file_id, caption=text[:1024] if text else None)
        else:
            if text:
                await self.bot.send_message(chat_id, text, link_preview_options=LinkPreviewOptions(is_disabled=True))
