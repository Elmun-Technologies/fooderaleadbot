"""Async engine / session factory.

The same code runs on PostgreSQL (``postgresql+asyncpg://``) and SQLite
(``sqlite+aiosqlite://``) - only ``DATABASE_URL`` changes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database.db_url import prepare_database_url
from app.database.models import Base

__all__ = ["Database", "create_database"]

logger = logging.getLogger(__name__)


class Database:
    """Thin wrapper around engine + session factory (easy to construct in tests)."""

    def __init__(
        self, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.engine = engine
        self.session_factory = session_factory

    @property
    def is_sqlite(self) -> bool:
        return self.engine.dialect.name == "sqlite"

    @classmethod
    def from_url(cls, url: str, *, echo: bool = False) -> Database:
        # `DATABASE_URL` from a PaaS dashboard carries libpq parameters that asyncpg has no
        # keyword for (`?sslmode=disable`) - they become `connect_args` instead of a TypeError.
        url, connect_args = prepare_database_url(url)
        kwargs: dict[str, object] = {"echo": echo, "future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            # a single shared connection keeps SQLite simple for local testing
            connect_args["check_same_thread"] = False
            if ":memory:" in url or "mode=memory" in url:
                kwargs["poolclass"] = StaticPool
        if connect_args:
            kwargs["connect_args"] = connect_args
        engine = create_async_engine(url, **kwargs)

        if engine.dialect.name == "sqlite":

            @event.listens_for(engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

        return cls(engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False))

    async def create_schema(self) -> None:
        """Create tables if they do not exist (dev / SQLite convenience)."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        logger.info("database schema ready", extra={"dialect": self.engine.dialect.name})

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session; rolls back on an unhandled exception."""
        session = self.session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def create_database(url: str, *, echo: bool = False) -> Database:
    return Database.from_url(url, echo=echo)
