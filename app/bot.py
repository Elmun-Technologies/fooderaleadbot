"""Bot and dispatcher assembly.

Everything Telegram-facing is created here: the :class:`Bot` (HTML parse mode, previews
off by default), FSM storage (memory by default, Redis when configured), the routers,
the middleware chain and the command menu.
"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from app.config import Settings
from app.database.session import Database
from app.handlers import on_error, routers
from app.middlewares import DatabaseMiddleware, ThrottlingMiddleware, UserContextMiddleware

__all__ = ["create_bot", "create_dispatcher", "create_storage", "setup_commands"]

logger = logging.getLogger(__name__)


class BotConfigError(RuntimeError):
    """Raised when the process is started without the minimum required configuration."""


def create_bot(settings: Settings) -> Bot:
    if not settings.requires_bot_token:
        raise BotConfigError(
            "BOT_TOKEN is empty. Create a bot with @BotFather, then put the token into .env "
            "(see the Setup section of the README)."
        )
    return Bot(
        token=settings.bot_token_value,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_storage(settings: Settings) -> BaseStorage:
    """In-memory by default; Redis when ``REDIS_URL`` is set (multi-instance / restarts)."""
    if settings.redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise BotConfigError(
                "REDIS_URL is set but the redis integration is unavailable. "
                "Install `redis` (pip install redis) or leave REDIS_URL empty."
            ) from exc
        logger.info("using Redis FSM storage")
        return RedisStorage.from_url(settings.redis_url)
    logger.info("using in-memory FSM storage (single instance)")
    return MemoryStorage()


def create_dispatcher(settings: Settings, database: Database, bot: Bot | None = None) -> Dispatcher:
    dispatcher = Dispatcher(storage=create_storage(settings))

    # outermost first: flood control must run before we touch the database
    dispatcher.update.outer_middleware(ThrottlingMiddleware(limit=settings.rate_limit_per_minute))
    dispatcher.update.outer_middleware(DatabaseMiddleware(database, settings))
    dispatcher.update.outer_middleware(UserContextMiddleware(settings))

    for router in routers():
        dispatcher.include_router(router)

    dispatcher.errors.register(on_error)
    dispatcher.startup.register(_log_start)
    return dispatcher


async def _log_start(dispatcher: Dispatcher, bot: Bot) -> None:
    try:
        me = await bot.get_me()
        logger.info("bot online as @%s (id=%s)", me.username, me.id)
    except Exception as exc:  # pragma: no cover - network
        logger.warning("could not fetch bot profile: %s", type(exc).__name__)


def command_list(language_code: str, settings: Settings) -> list[BotCommand]:
    from app.i18n import t

    commands = [
        BotCommand(command="start", description=t("welcome.cta", language_code)[:256]),
        BotCommand(
            command="restart", description=t("btn.restart", language_code).replace("🔄 ", "")[:256]
        ),
        BotCommand(
            command="help", description=t("btn.support", language_code).replace("❓ ", "")[:256]
        ),
    ]
    if settings.admin_user_ids:
        commands += [
            BotCommand(command="stats", description="Leads overview"),
            BotCommand(command="leads", description="Latest leads"),
            BotCommand(command="hot", description="HOT leads"),
            BotCommand(command="warm", description="WARM leads"),
            BotCommand(command="today", description="Leads today"),
            BotCommand(command="source", description="Source / campaign performance"),
        ]
    return commands


async def setup_commands(bot: Bot, settings: Settings) -> None:
    """Language-aware command menu for private chats; only /chatid-ish commands in groups."""
    for language_code in ("uz", "ru"):
        try:
            await bot.set_my_commands(
                command_list(language_code, settings),
                scope=BotCommandScopeAllPrivateChats(),
                language_code=language_code,
            )
        except Exception as exc:  # pragma: no cover - network
            logger.warning("could not set commands for %s: %s", language_code, type(exc).__name__)
    try:
        await bot.set_my_commands(
            [BotCommand(command="help", description="FOODERA EXPO 2026")],
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception as exc:  # pragma: no cover - network
        logger.debug("could not set group commands: %s", type(exc).__name__)
