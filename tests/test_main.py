"""Startup behaviour of ``python -m app.main``.

Exit codes are part of the operator interface (systemd's ``Restart=`` reacts to them) and so is
the "we could not start, here is the fix" message, so those paths are asserted here instead of
by hand.  The dispatcher itself is a stub: the real routers are module singletons and can only
be attached once per process (``tests/test_journey.py`` owns the wired-up version).
"""

from __future__ import annotations

from typing import Any

import app.main as main_module
import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe
from app.config import Settings


class RecordingEvents:
    def __init__(self) -> None:
        self.registered: list[Any] = []

    def register(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.registered.append(callback)


class StubDispatcher:
    """Just enough of a :class:`aiogram.Dispatcher` for ``run()`` to drive it."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.startup = RecordingEvents()
        self.shutdown = RecordingEvents()
        self.poll_kwargs: dict[str, Any] = {}
        self.poll_args: tuple[Any, ...] = ()
        self._error = error

    def resolve_used_update_types(self) -> list[str]:
        return ["message", "callback_query"]

    async def start_polling(self, *args: Any, **kwargs: Any) -> None:
        if self._error is not None:
            raise self._error
        self.poll_args = args
        self.poll_kwargs = kwargs


@pytest.fixture(autouse=True)
def _quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "setup_logging", lambda *args, **kwargs: None)


def make_settings(tmp_path, **kwargs: Any) -> Settings:
    values: dict[str, Any] = {
        "bot_token": "123456:test-token-abcdefg",
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'main.db'}",
        "auto_create_tables": True,
    }
    values.update(kwargs)
    return Settings(_env_file=None, **values)


def use_stub(monkeypatch: pytest.MonkeyPatch, dispatcher: StubDispatcher) -> StubDispatcher:
    monkeypatch.setattr(
        main_module, "create_dispatcher", lambda settings, database, bot: dispatcher
    )
    return dispatcher


class TestStartupOutcomes:
    async def test_missing_token_exits_with_a_configuration_error(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            main_module, "get_settings", lambda: make_settings(tmp_path, bot_token="")
        )
        assert await main_module.run() == 2

    async def test_unreachable_telegram_exits_with_a_network_error(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(main_module, "get_settings", lambda: make_settings(tmp_path))
        network_error = TelegramNetworkError(
            method=GetMe(), message="cannot connect to host api.telegram.org"
        )
        use_stub(monkeypatch, StubDispatcher(error=network_error))
        assert await main_module.run() == 4

    async def test_missing_schema_is_reported_with_the_fix(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            main_module, "get_settings", lambda: make_settings(tmp_path, auto_create_tables=False)
        )
        assert await main_module.run() == 3

    async def test_schema_check_happens_before_polling(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatcher = use_stub(monkeypatch, StubDispatcher())
        monkeypatch.setattr(main_module, "get_settings", lambda: make_settings(tmp_path))
        assert await main_module.run() == 0
        assert len(dispatcher.startup.registered) == 1  # the command-menu hook
        assert len(dispatcher.shutdown.registered) == 1  # and the engine dispose

    async def test_polling_asks_only_for_the_update_types_in_use(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dispatcher = use_stub(monkeypatch, StubDispatcher())
        monkeypatch.setattr(main_module, "get_settings", lambda: make_settings(tmp_path))
        assert await main_module.run() == 0
        assert {"message", "callback_query"} == set(dispatcher.poll_kwargs["allowed_updates"])
        assert dispatcher.poll_kwargs["close_bot_session"] is True
        assert dispatcher.poll_args[0] is not None  # the Bot instance

    async def test_a_starter_without_a_sales_group_only_warns(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No SALES_GROUP_ID is a supported (warned about) configuration, not a crash."""
        monkeypatch.setattr(
            main_module, "get_settings", lambda: make_settings(tmp_path, sales_group_id=None)
        )
        use_stub(monkeypatch, StubDispatcher())
        with caplog.at_level("WARNING"):
            assert await main_module.run() == 0
        assert any("SALES_GROUP_ID is empty" in record.message for record in caplog.records)
        assert any("ADMIN_USER_IDS is empty" in record.message for record in caplog.records)

    async def test_postgres_with_auto_create_is_flagged(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = make_settings(tmp_path, database_url="postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.setattr(main_module, "get_settings", lambda: settings)
        monkeypatch.setattr(main_module, "create_database", lambda url, **kwargs: _FakeDatabase())
        use_stub(monkeypatch, StubDispatcher())
        with caplog.at_level("WARNING"):
            assert await main_module.run() == 0
        assert any("alembic upgrade head" in record.message for record in caplog.records)


class _FakeDatabase:
    """Stands in for :class:`app.database.session.Database` when there is no Postgres here."""

    async def create_schema(self) -> None:
        return None

    async def dispose(self) -> None:
        return None
