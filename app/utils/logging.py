"""Structured logging setup (human readable locally, JSON in production)."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

__all__ = ["ConsoleFormatter", "JsonFormatter", "redact", "setup_logging"]

LOG_RECORD_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# Keys whose values must never reach the log output.
_SENSITIVE_KEYS = (
    "bot_token",
    "token",
    "password",
    "secret",
    "redis_url",
    "database_url",
    "api_key",
)

_BOT_TOKEN_IN_TEXT = re.compile(r"\b\d{6,10}:[A-Za-z0-9_-]{30,}\b")

NOISY_LOGGERS = {
    "aiogram.dispatcher": "INFO",
    "aiogram.event": "WARNING",
    "aiogram.middlewares": "WARNING",
    "aiogram.bot": "WARNING",
    "aiogram.utils.token": "WARNING",
    "asyncio": "WARNING",
    "aiosqlite": "WARNING",
}


def redact(value: Any) -> Any:
    """Best-effort masking of credential-looking values."""
    if isinstance(value, dict):
        return {
            key: (
                "***" if any(word in str(key).lower() for word in _SENSITIVE_KEYS) else redact(val)
            )
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str) and _BOT_TOKEN_IN_TEXT.search(value):
        # A bot token pasted into a log message must never leak.
        return _BOT_TOKEN_IN_TEXT.sub("***", value)
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line - friendly to journald / Loki / ELK."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        extras = _extras(record)
        if extras:
            payload["data"] = redact(extras)
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Compact single-line format for development."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} {record.levelname:<7} {record.name}: {record.getMessage()}"
        extras = _extras(record)
        if extras:
            line += f" | {redact(extras)}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in LOG_RECORD_RESERVED and not key.startswith("_")
    }


def setup_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Configure the root logger. Idempotent, safe to call from tests."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else ConsoleFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))

    for name, noisy_level in NOISY_LOGGERS.items():
        logging.getLogger(name).setLevel(getattr(logging, noisy_level, logging.INFO))
