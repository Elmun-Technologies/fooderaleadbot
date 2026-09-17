"""Dependencies for web admin."""

from __future__ import annotations

from fastapi import Depends

from app.config import Settings, get_settings
from app.database.session import Database, create_database
from app.database.repository import LeadRepository

# Global database instance for web (will be set on startup)
_db: Database | None = None


def get_database(settings: Settings = Depends(get_settings)) -> Database:
    global _db
    if _db is None:
        _db = create_database(settings.database_url, echo=settings.sql_echo)
    return _db


async def get_repo(settings: Settings = Depends(get_settings)):
    db = get_database(settings)
    async with db.session() as session:
        repo = LeadRepository(session)
        yield repo


def get_bot(settings: Settings = Depends(get_settings)):
    # Bot will be injected via app state
    from app.web.app import get_bot_instance

    return get_bot_instance()
