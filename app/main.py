"""Process entry point.

    python -m app.main

Long polling by default (no public URL, no TLS certificates - the simplest reliable
setup for a lead bot behind Telegram Ads traffic).
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from sqlalchemy import text

from app.bot import BotConfigError, create_bot, create_dispatcher, setup_commands
from app.config import Settings, get_settings
from app.database.session import Database, create_database
from app.utils.logging import setup_logging

__all__ = ["main", "run"]

logger = logging.getLogger("app.main")


def validate_settings(settings: Settings) -> None:
    """Warn loudly (but do not crash) about configuration that will hurt in production."""
    if not settings.sales_group_id:
        logger.warning(
            "SALES_GROUP_ID is empty - qualified leads will be saved to the database but NOT "
            "forwarded to any group. Add the bot to the sales group and set the chat id."
        )
    if not settings.admin_user_ids:
        logger.warning("ADMIN_USER_IDS is empty - admin commands are unreachable.")
    if settings.auto_create_tables and not settings.database_url.startswith("sqlite"):
        logger.warning(
            "AUTO_CREATE_TABLES=true with PostgreSQL: prefer `alembic upgrade head` and set "
            "AUTO_CREATE_TABLES=false in production."
        )
    if settings.require_phone_for_sales and settings.qualify_min_classification == "hot":
        logger.info("strict mode: only HOT leads with a phone number are pushed to the sales group")


async def assert_schema_ready(database: Database) -> None:
    """Fail fast with an actionable message instead of crashing on the first lead."""
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1 FROM leads"))
    except Exception as exc:
        hint = "Run `alembic upgrade head` (or set AUTO_CREATE_TABLES=true for local testing)."
        raise RuntimeError(f"database schema is not ready: {type(exc).__name__}. {hint}") from exc


async def run() -> int:
    settings = get_settings()
    setup_logging(settings.log_level, json_output=settings.log_json)

    logger.info(
        "starting FOODERA lead bot",
        extra={
            "database": settings.database_url.split("://", 1)[0],
            "sales_group": settings.sales_group_id,
            "admins": len(settings.admin_user_ids),
            "default_language": settings.default_language,
            "admin_panel": settings.admin_panel_enabled,
            "thresholds": {
                "hot": settings.hot_min_score,
                "warm": settings.warm_min_score,
                "cold": settings.cold_min_score,
                "push_from": settings.qualify_min_classification,
            },
        },
    )
    validate_settings(settings)

    database = create_database(settings.database_url, echo=settings.sql_echo)
    web_task = None
    try:
        if settings.auto_create_tables:
            await database.create_schema()
        else:
            await assert_schema_ready(database)

        bot = create_bot(settings)
        dispatcher: Dispatcher = create_dispatcher(settings, database, bot)

        async def _on_startup(bot: Bot, dispatcher: Dispatcher) -> None:
            await setup_commands(bot, settings)

        dispatcher.startup.register(_on_startup)

        async def _on_shutdown(bot: Bot, dispatcher: Dispatcher) -> None:
            await database.dispose()

        dispatcher.shutdown.register(_on_shutdown)

        # Start admin panel if enabled
        if settings.admin_panel_enabled:
            try:
                from app.web.app import app as web_app, set_bot_instance
                import uvicorn

                set_bot_instance(bot)

                # Set database for web
                from app.web.deps import _db as _web_db_module

                import app.web.deps as web_deps

                web_deps._db = database

                config = uvicorn.Config(
                    web_app,
                    host=settings.admin_panel_host,
                    port=settings.admin_panel_port,
                    log_level="info",
                    access_log=False,
                )
                server = uvicorn.Server(config)

                async def _run_web():
                    logger.info(
                        "starting admin panel on %s:%s",
                        settings.admin_panel_host,
                        settings.admin_panel_port,
                    )
                    await server.serve()

                web_task = asyncio.create_task(_run_web())
                logger.info("admin panel enabled at http://%s:%s/admin", settings.admin_panel_host, settings.admin_panel_port)
            except Exception as exc:
                logger.warning("could not start admin panel: %s", exc)

        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            close_bot_session=True,
        )
        return 0
    except BotConfigError as exc:
        logger.error("configuration error: %s", exc)
        return 2
    except TelegramUnauthorizedError:
        logger.error(
            "Telegram rejected BOT_TOKEN (401 Unauthorized). Check that .env contains the token "
            "@BotFather issued for this exact bot, without quotes or the @username part."
        )
        return 2
    except TelegramNetworkError as exc:
        logger.error(
            "cannot reach api.telegram.org (%s). The bot only needs outbound HTTPS:443 - "
            "check DNS, the firewall or an egress proxy (set HTTPS_PROXY).",
            exc,
        )
        return 4
    except RuntimeError as exc:
        logger.error("startup failed: %s", exc)
        return 3
    finally:
        if web_task:
            web_task.cancel()
            try:
                await web_task
            except asyncio.CancelledError:
                pass
        await database.dispose()
        logger.info("bot stopped")


def main() -> int:
    """Console entry point: ``python -m app.main``."""
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover - Ctrl+C / systemd stop
        logger.info("interrupted, shutting down")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
