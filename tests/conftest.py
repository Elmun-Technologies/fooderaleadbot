"""Shared pytest fixtures.

Tests never talk to Telegram: the service layer is exercised directly and a recording
fake stands in for :class:`LeadNotifier`, so the whole qualification + notification
decision path is covered in milliseconds against SQLite.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.database.models import BotUser, Lead  # noqa: E402
from app.database.repository import LeadRepository  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.services.lead_service import LeadService  # noqa: E402

SALES_CHAT = -1001234567890


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123456:TEST-token-not-a-real-one",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        sales_group_id=SALES_CHAT,
        sales_group_topic_id=None,
        visitor_group_id=None,
        admin_user_ids=[111],
        default_language="uz",
        support_username="foodera_support",
        display_timezone="UTC",
        auto_create_tables=True,
    )


@pytest.fixture
async def database(settings: Settings):
    database = Database.from_url(settings.database_url)
    await database.create_schema()
    yield database
    await database.dispose()


@pytest.fixture
async def session(database: Database):
    async with database.session() as session:
        yield session


@pytest.fixture
async def repo(session) -> LeadRepository:
    return LeadRepository(session)


class FakeNotifier:
    """Records what would have been sent to the sales / visitor groups."""

    def __init__(self, settings: Settings, *, visitor_group: bool = False) -> None:
        self.settings = settings
        self.sent: list[Lead] = []
        self.visitor_sent: list[Lead] = []
        self.edited: list[int] = []
        self.locked: list[tuple[int, str]] = []
        self._visitor_group = visitor_group
        self.cards: dict[int, str] = {}

    @property
    def sales_target(self) -> tuple[int, int | None]:
        return self.settings.sales_group_id, self.settings.sales_group_topic_id

    @property
    def visitor_target(self) -> tuple[int, int | None] | None:
        if not self._visitor_group:
            return None
        return -1009876543210, None

    def card_language(self, lead: Lead) -> str:
        return self.settings.card_language_for(lead.language)

    async def send_lead_card(self, lead: Lead) -> _FakeMessage:
        self.sent.append(lead)
        return _FakeMessage(
            chat_id=self.settings.sales_group_id or 0, message_id=100 + len(self.sent)
        )

    async def send_visitor_card(self, lead: Lead) -> _FakeMessage:
        self.visitor_sent.append(lead)
        return _FakeMessage(chat_id=-1, message_id=900 + len(self.visitor_sent))

    async def update_lead_card(self, lead: Lead) -> bool:
        self.edited.append(lead.id)
        return True

    async def lock_card(self, lead: Lead, note: str) -> None:
        self.locked.append((lead.id, note))

    def allows_manager(self, user_id: int, chat_id: int | None) -> bool:
        return chat_id == self.settings.sales_group_id or user_id in self.settings.admin_user_ids

    async def alert_admins(self, text: str) -> None:  # pragma: no cover - not asserted
        return None


class _FakeMessage:
    def __init__(self, chat_id: int, message_id: int) -> None:
        self.chat = _FakeChat(chat_id)
        self.message_id = message_id


class _FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


@pytest.fixture
def notifier(settings: Settings) -> FakeNotifier:
    return FakeNotifier(settings)


@pytest.fixture
def notifier_with_visitor_group(settings: Settings) -> FakeNotifier:
    return FakeNotifier(settings, visitor_group=True)


@pytest.fixture
async def leads(repo: LeadRepository, settings: Settings, notifier: FakeNotifier) -> LeadService:
    return LeadService(repo, settings, notifier)  # type: ignore[arg-type]


@pytest.fixture
async def user(repo: LeadRepository) -> BotUser:
    return await repo.get_or_create_user(
        4242,
        username="azizbek",
        first_name="Azizbek",
        last_name="Karimov",
        defaults={
            "language": "uz",
            "language_explicit": True,
            "source": "telegram_ads",
            "campaign": "foodera",
            "creative": "uz_01",
            "start_payload": "tgads_foodera_uz_01",
        },
    )


def answer_payload(**values: Any) -> dict[str, Any]:
    """Helper for tests: a dict of lead fields."""
    return dict(values)
