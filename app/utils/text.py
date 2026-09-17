"""Small text helpers: Telegram-safe escaping, truncation, time formatting."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

__all__ = [
    "clean_text",
    "esc",
    "format_datetime",
    "local_now",
    "mask_phone",
    "or_dash",
    "truncate",
]

_CONTROL_CHARS = re.compile(r"[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028\u2029\ufeff]")
_WHITESPACE = re.compile(r"\s+")


def esc(value: Any) -> str:
    """Escape a value for Telegram HTML parse mode."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def clean_text(value: Any, *, max_len: int | None = 120, collapse_ws: bool = True) -> str:
    """Strip control characters, normalise whitespace and clamp the length.

    Users paste all kinds of junk (emoji ZWJ sequences, zero width chars, newlines),
    and Telegram HTML breaks on stray control characters.
    """
    if value is None:
        return ""
    text = _CONTROL_CHARS.sub("", str(value)).strip()
    if collapse_ws:
        text = _WHITESPACE.sub(" ", text)
    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "\u2026"
    return text


def truncate(value: Any, max_len: int = 60) -> str:
    text = str(value or "")
    return text if len(text) <= max_len else text[: max_len - 1] + "\u2026"


def or_dash(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "\u2014"


def mask_phone(phone: str | None) -> str:
    """Keep phone numbers out of plain log output."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return "*" * len(digits)
    return (
        f"+{digits[:2]}***{digits[-4:]}"
        if phone.startswith("+")
        else f"{digits[:2]}***{digits[-4:]}"
    )


@lru_cache
def _zone_info(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except Exception:  # pragma: no cover - depends on system tzdata
        return None


def local_now(timezone_name: str | None = None) -> datetime:
    now = datetime.now(UTC)
    if timezone_name:
        zone = _zone_info(timezone_name)
        if zone is not None:
            return now.astimezone(zone)
    return now


def format_datetime(value: datetime | None, timezone_name: str | None = None) -> str:
    """``17.09.2026 14:30`` - the format managers expect."""
    if value is None:
        return "\u2014"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if timezone_name:
        zone = _zone_info(timezone_name)
        if zone is not None:
            value = value.astimezone(zone)
    return value.strftime("%d.%m.%Y %H:%M")
