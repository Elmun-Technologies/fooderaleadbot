"""Settings: env parsing, validation and secret hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings, get_settings


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


class TestAdminIds:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("111,222", [111, 222]),
            ("111, 222 333", [111, 222, 333]),
            ("111;222", [111, 222]),
            (111, [111]),
            ([111, 222], [111, 222]),
            ("", []),
            (None, []),
            ("111,111", [111]),
        ],
    )
    def test_parsing(self, raw: object, expected: list[int]) -> None:
        assert make(admin_user_ids=raw).admin_user_ids == expected

    def test_usernames_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="numeric"):
            make(admin_user_ids="@azizbek")


class TestDatabaseUrl:
    @pytest.mark.parametrize(
        ("raw", "expected_prefix"),
        [
            ("postgresql://u:p@localhost/db", "postgresql+asyncpg://"),
            ("postgres://u:p@localhost/db", "postgresql+asyncpg://"),
            ("postgresql+asyncpg://u:p@localhost/db", "postgresql+asyncpg://"),
            ("sqlite:///./bot.db", "sqlite+aiosqlite:///"),
            ("sqlite+pysqlite:////data/foodera.db", "sqlite+aiosqlite:////data/"),
            # what a PaaS hands you, verbatim
            (
                "postgres://foodera:S3cr3t@666.internal.fly.dev:5432/foodera_leads?sslmode=disable",
                "postgresql+asyncpg://foodera:",
            ),
            ("postgresql+psycopg://u:p@localhost/db", "postgresql+asyncpg://"),
            ("postgresql+psycopg2://u:p@localhost/db", "postgresql+asyncpg://"),
        ],
    )
    def test_async_driver_is_forced(self, raw: str, expected_prefix: str) -> None:
        assert make(database_url=raw).database_url.startswith(expected_prefix)

    def test_default_is_sqlite(self) -> None:
        assert make().database_url.startswith("sqlite+aiosqlite")

    def test_garbage_url_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            make(database_url="not-a-url")


class TestGroupIds:
    def test_blank_values_become_none(self) -> None:
        settings = make(sales_group_id="", sales_group_topic_id="", visitor_group_id="")
        assert settings.sales_group_id is None
        assert settings.sales_group_topic_id is None
        assert settings.visitor_group_id is None

    def test_negative_supergroup_ids(self) -> None:
        settings = make(sales_group_id="-1001234567890", sales_group_topic_id="42")
        assert settings.sales_group_id == -1001234567890
        assert settings.sales_group_topic_id == 42

    def test_topics_are_optional(self) -> None:
        assert make(sales_group_id="-1001").sales_group_topic_id is None


class TestThresholds:
    def test_defaults_match_the_specification(self) -> None:
        settings = make()
        assert (settings.hot_min_score, settings.warm_min_score, settings.cold_min_score) == (
            75,
            55,
            35,
        )
        assert settings.qualify_min_classification == "warm"
        assert settings.require_phone_for_sales is True
        assert settings.require_company_name_for_sales is True

    def test_inconsistent_thresholds_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="COLD_MIN_SCORE"):
            make(hot_min_score=40, warm_min_score=60)

    def test_custom_thresholds_are_accepted(self) -> None:
        settings = make(hot_min_score=90, warm_min_score=70, cold_min_score=50)
        assert settings.warm_min_score == 70

    def test_invalid_language_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            make(default_language="de")

    def test_zero_rate_limit_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            make(rate_limit_per_minute=0)


class TestSecrets:
    def test_token_is_not_printed(self) -> None:
        settings = make(bot_token="123456:secret-token-value-abcdef")
        assert "secret-token-value" not in repr(settings)
        assert "secret-token-value" not in str(settings)

    def test_masked_dict_hides_the_token(self) -> None:
        settings = make(bot_token="123456:secret-token-value-abcdef")
        assert settings.masked_dict()["bot_token"] == "***"
        assert settings.bot_token_value == "123456:secret-token-value-abcdef"

    def test_empty_token_detection(self) -> None:
        assert make(bot_token="").requires_bot_token is False
        assert make(bot_token=" 123:abc ").requires_bot_token is True

    def test_token_whitespace_is_stripped(self) -> None:
        assert make(bot_token=" 123:abc\n").bot_token_value == "123:abc"


class TestCardLanguage:
    def test_auto_follows_the_lead(self) -> None:
        settings = make(sales_card_language="auto", default_language="uz")
        assert settings.card_language_for("ru") == "ru"
        assert settings.card_language_for("uz") == "uz"
        assert settings.card_language_for(None) == "uz"
        assert settings.card_language_for("de") == "uz"

    def test_forced_language_wins(self) -> None:
        settings = make(sales_card_language="ru")
        assert settings.card_language_for("uz") == "ru"


class TestTimezone:
    def test_unknown_timezone_falls_back_to_utc(self) -> None:
        assert make(display_timezone="Mars/Olympus").display_timezone == "UTC"

    def test_real_timezone_is_kept(self) -> None:
        assert make(display_timezone="Asia/Tashkent").display_timezone in {"Asia/Tashkent", "UTC"}

    def test_lead_code_prefix_is_normalised(self) -> None:
        assert make(lead_code_prefix=" fd ").lead_code_prefix == "FD"


class TestEnvironmentFile:
    def test_dotenv_is_picked_up(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "BOT_TOKEN=999:from-dotenv\nADMIN_USER_IDS=1,2\nLOG_LEVEL=DEBUG\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        settings = Settings()
        assert settings.bot_token_value == "999:from-dotenv"
        assert settings.admin_user_ids == [1, 2]
        assert settings.log_level == "DEBUG"

    def test_get_settings_is_cached(self) -> None:
        assert get_settings() is get_settings()


class TestEnvExample:
    """``.env.example`` is the operational contract: every knob has to be documented."""

    ENV_FILE = Path(__file__).resolve().parents[1] / ".env.example"

    @property
    def documented(self) -> set[str]:
        keys: set[str] = set()
        for line in self.ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                keys.add(stripped.split("=", 1)[0].strip().upper())
        return keys

    def test_every_setting_is_documented(self) -> None:
        missing = {name.upper() for name in Settings.model_fields} - self.documented
        assert not missing, f".env.example does not mention: {sorted(missing)}"

    def test_no_undocumented_keys_are_advertised(self) -> None:
        unknown = self.documented - {name.upper() for name in Settings.model_fields}
        assert not unknown, f".env.example documents unknown settings: {sorted(unknown)}"

    def test_the_token_ships_empty(self) -> None:
        text = self.ENV_FILE.read_text(encoding="utf-8")
        assert "BOT_TOKEN=\n" in text, "never put a real token in the example file"
