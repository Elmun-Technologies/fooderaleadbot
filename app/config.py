"""Application settings.

Everything is configured through environment variables (optionally loaded from a
``.env`` file).  No secrets are ever hardcoded.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["SUPPORTED_LANGUAGES", "Settings", "get_settings"]

SUPPORTED_LANGUAGES: tuple[str, ...] = ("uz", "ru")

_ID_SEPARATOR = re.compile(r"[,\s;]+")
_DATABASE_URL_ALIASES = (
    ("postgres://", "postgresql+asyncpg://"),
    ("postgresql://", "postgresql+asyncpg://"),
    # PaaS dashboards (Fly.io, Supabase, Neon, Heroku) hand out `postgres://…` URLs and docs
    # often show the sync psycopg drivers; the bot only speaks asyncpg.
    ("postgresql+psycopg://", "postgresql+asyncpg://"),
    ("postgresql+psycopg2://", "postgresql+asyncpg://"),
    ("sqlite://", "sqlite+aiosqlite://"),
    ("sqlite+pysqlite://", "sqlite+aiosqlite://"),
)


def _as_int_list(raw: Any) -> list[int]:
    """Parse ``"123, 456"`` / ``"123 456"`` / ``[123, 456]`` into ``[123, 456]``."""
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, (list, tuple, set, frozenset)):
        items: list[Any] = list(raw)
    else:
        items = [part for part in _ID_SEPARATOR.split(str(raw).strip()) if part]

    result: list[int] = []
    for item in items:
        value = str(item).strip()
        if value.startswith("@"):
            raise ValueError(
                f"Telegram ids must be numeric, got username {value!r}. "
                "Resolve the numeric id first (e.g. with @userinfobot)."
            )
        result.append(int(value))
    # de-duplicate, keep order, drop zeros
    return [value for value in dict.fromkeys(result) if value]


class Settings(BaseSettings):
    """Runtime configuration (1 class == 1 env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ Telegram
    bot_token: SecretStr = SecretStr("")
    bot_username: str | None = None

    # ----------------------------------------------------------------- Database
    database_url: str = "sqlite+aiosqlite:///./foodera_bot.db"
    auto_create_tables: bool = True
    sql_echo: bool = False
    redis_url: str | None = None

    # ------------------------------------------------------------------- Groups
    sales_group_id: int | None = None
    sales_group_topic_id: int | None = None
    visitor_group_id: int | None = None
    visitor_group_topic_id: int | None = None
    sales_card_language: Literal["auto", "uz", "ru"] = "auto"

    # --------------------------------------------------------------------- ACLS
    #: ``NoDecode`` keeps the raw string so our parser can accept "1,2 3" as well as JSON
    admin_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    allow_group_managers: bool = True

    # ---------------------------------------------------------------- Behaviour
    default_language: Literal["uz", "ru"] = "uz"
    log_level: str = "INFO"
    log_json: bool = False
    support_username: str | None = None
    display_timezone: str = "Asia/Tashkent"
    lead_code_prefix: str = "FD"

    # ------------------------------------------------------- Qualification rule
    hot_min_score: int = 75
    warm_min_score: int = 55
    cold_min_score: int = 35
    qualify_min_classification: Literal["cold", "warm", "hot"] = "warm"
    require_phone_for_sales: bool = True
    require_company_name_for_sales: bool = True

    # ---------------------------------------------------------------- Anti-spam
    recent_application_hours: int = 24
    draft_ttl_hours: int = 72
    rate_limit_per_minute: int = 30

    # ------------------------------------------------------------- validators
    @field_validator("bot_token", mode="before")
    @classmethod
    def _clean_token(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().strip('"').strip("'")
        return value

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> list[int]:
        return _as_int_list(value)

    @field_validator("sales_group_id", "visitor_group_id", mode="before")
    @classmethod
    def _parse_chat_id(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, str):
            value = value.strip().replace("@", "")
        return int(value)

    @field_validator(
        "sales_group_topic_id",
        "visitor_group_topic_id",
        "hot_min_score",
        "warm_min_score",
        "cold_min_score",
        "recent_application_hours",
        "draft_ttl_hours",
        "rate_limit_per_minute",
        mode="before",
    )
    @classmethod
    def _blank_to_none_int(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        """Make sure an async driver is used, whatever the operator wrote."""
        value = value.strip()
        for prefix, replacement in _DATABASE_URL_ALIASES:
            if value.startswith(prefix):
                return replacement + value[len(prefix) :]
        if value.startswith("postgres+"):  # postgres+psycopg -> asyncpg
            return "postgresql+asyncpg://" + value.split("://", 1)[1]
        if "://" not in value:
            raise ValueError(
                "DATABASE_URL must be a SQLAlchemy URL, e.g. "
                "postgresql+asyncpg://user:pass@host/db or sqlite+aiosqlite:///./bot.db"
            )
        return value

    @field_validator("display_timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        from zoneinfo import available_timezones

        if value not in available_timezones():
            # Non fatal (slim images may ship without tzdata) - fall back to UTC.
            return "UTC"
        return value

    @model_validator(mode="after")
    def _consistent_thresholds(self) -> Settings:
        if not 0 < self.cold_min_score <= self.warm_min_score <= self.hot_min_score <= 100:
            raise ValueError(
                "Score thresholds must satisfy 0 < COLD_MIN_SCORE <= WARM_MIN_SCORE "
                f"<= HOT_MIN_SCORE <= 100 (got {self.cold_min_score}/{self.warm_min_score}"
                f"/{self.hot_min_score})"
            )
        for name in ("recent_application_hours", "draft_ttl_hours", "rate_limit_per_minute"):
            if getattr(self, name) is not None and getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        prefix = (self.lead_code_prefix or "FD").strip().upper()
        self.lead_code_prefix = prefix or "FD"
        return self

    # ------------------------------------------------------------- convenience
    @property
    def bot_token_value(self) -> str:
        return self.bot_token.get_secret_value()

    @property
    def requires_bot_token(self) -> bool:
        return bool(self.bot_token_value)

    def masked_dict(self) -> dict[str, Any]:
        """Safe-to-log view of the configuration (secrets masked)."""
        data = self.model_dump(mode="json")
        data["bot_token"] = "***" if self.bot_token_value else ""
        return data

    def __repr__(self) -> str:  # pragma: no cover - defensive against log leaks
        return f"Settings(bot_token='***', database_url={self.database_url!r})"

    def card_language_for(self, lead_language: str | None) -> str:
        """Language used for the sales-group lead card."""
        if self.sales_card_language != "auto":
            return self.sales_card_language
        return lead_language if lead_language in SUPPORTED_LANGUAGES else self.default_language


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (reload with ``get_settings.cache_clear()``)."""
    return Settings()
