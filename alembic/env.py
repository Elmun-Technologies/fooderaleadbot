"""Alembic environment.

Uses the application settings (``DATABASE_URL`` from ``.env``) and the async engine, so
migrations behave identically on PostgreSQL and SQLite and never need a URL of their own.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# make the project importable when alembic is invoked from the repository root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.database.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
database_url = os.getenv("DATABASE_URL") or settings.database_url
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def _is_async(url: str) -> bool:
    return "+aiosqlite" in url or "+asyncpg" in url or "+aiomysql" in url


def run_migrations_offline() -> None:
    """Emit SQL to a file (`alembic upgrade head --sql`) - no DB connection needed."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite cannot ALTER columns in place
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    if _is_async(database_url):
        asyncio.run(run_async_migrations())
        return

    from sqlalchemy import create_engine

    connectable = create_engine(database_url, poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
