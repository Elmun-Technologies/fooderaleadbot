"""Named tracking links for ads ("Reklama linklari").

The simple flow:

1. An admin creates a link in the panel (or with ``/link``) by giving it a NAME,
   e.g. "Instagram dekabr" - nothing else to remember.
2. We slugify the name into a payload (``instagram_dekabr``) and store the row in
   the ``tracking_links`` table together with the chosen source.
3. The ad uses ``https://t.me/<bot>?start=instagram_dekabr``.
4. On ``/start`` the bot looks the payload up in the table FIRST - the stored
   source/campaign win over grammar parsing, so attribution is always exact.
5. The panel (and ``/link`` with no arguments) shows per-link stats:
   starts -> applications -> qualified.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.source_tracking import SourceInfo, parse_start_payload

__all__ = [
    "SOURCE_CHOICES",
    "build_deep_link",
    "detect_source",
    "resolve_source",
    "slugify",
    "source_choice_label",
    "unique_payload",
]

#: source value stored on the link -> label shown in the panel form (uz / ru)
SOURCE_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("telegram_ads", "Telegram Ads", "Telegram Ads"),
    ("telegram_channel", "Telegram kanal / post", "Telegram канал / пост"),
    ("instagram", "Instagram", "Instagram"),
    ("facebook", "Facebook", "Facebook"),
    ("qr", "QR kod / banner", "QR код / баннер"),
    ("website", "Veb-sayt", "Веб-сайт"),
    ("partner", "Hamkor", "Партнёр"),
    ("other", "Boshqa", "Другое"),
)

_VALID_SOURCES = {key for key, _, _ in SOURCE_CHOICES}

#: keywords in a link name that let ``/link`` guess the source automatically
_SOURCE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("instagram", "instagram"),
    ("insta", "instagram"),
    ("facebook", "facebook"),
    ("kanal", "telegram_channel"),
    ("channel", "telegram_channel"),
    ("post", "telegram_channel"),
    ("ads", "telegram_ads"),
    ("tgads", "telegram_ads"),
    ("reklama", "telegram_ads"),
    ("qr", "qr"),
    ("banner", "qr"),
    ("sayt", "website"),
    ("site", "website"),
    ("web", "website"),
    ("hamkor", "partner"),
    ("partner", "partner"),
)

# Cyrillic -> Latin (covers Russian + Uzbek Cyrillic letters)
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}

MAX_PAYLOAD = 64  # Telegram limit for the start parameter


def slugify(title: str) -> str:
    """``"Instagram — Yangi yil aksiyasi!"`` -> ``"instagram_yangi_yil_aksiyasi"``."""
    text = (title or "").strip().lower()
    text = "".join(_TRANSLIT.get(ch, ch) for ch in text)
    text = text.replace("'", "").replace("\u02bc", "").replace("\u2018", "").replace("\u2019", "")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:MAX_PAYLOAD].strip("_")


def unique_payload(base: str, taken: set[str]) -> str:
    """Append ``_2``, ``_3``… until the payload is free."""
    payload = base or "link"
    if payload not in taken:
        return payload
    for n in range(2, 1000):
        suffix = f"_{n}"
        candidate = payload[: MAX_PAYLOAD - len(suffix)].rstrip("_") + suffix
        if candidate not in taken:
            return candidate
    return payload[: MAX_PAYLOAD - 8].rstrip("_") + "_x"  # pragma: no cover


def build_deep_link(bot_username: str, payload: str) -> str:
    return f"https://t.me/{bot_username.lstrip('@')}?start={payload}"


def detect_source(title: str) -> str:
    """Guess the source from the link name ("Instagram dekabr" -> instagram)."""
    words = re.split(r"[^a-z0-9]+", (title or "").lower())
    for word in words:
        for keyword, source in _SOURCE_KEYWORDS:
            if word == keyword:
                return source
    return "other"


def normalize_source(value: str | None) -> str:
    value = (value or "").strip().lower()
    return value if value in _VALID_SOURCES else "other"


def source_choice_label(source: str, lang: str = "uz") -> str:
    for key, uz, ru in SOURCE_CHOICES:
        if key == source:
            return ru if lang == "ru" else uz
    return source.replace("_", " ").title()


async def resolve_source(repo: Any, raw_payload: str | None) -> SourceInfo:
    """Attribution for ``/start``: the tracking-links table wins, parsing is the fallback.

    If the payload matches a saved link, the stored source/campaign are exact -
    no grammar guessing. Unknown payloads still go through ``parse_start_payload``
    so nothing is ever lost.
    """
    info = parse_start_payload(raw_payload)
    if not raw_payload:
        return info
    key = str(raw_payload).strip().lower()[:MAX_PAYLOAD]
    try:
        link = await repo.tracking_link_by_payload(key)
    except Exception:  # pragma: no cover - attribution must never break /start
        return info
    if link is None:
        return info
    return SourceInfo(
        start_payload=info.start_payload,
        source=link.source,
        campaign=link.payload,
        creative=None,
        parsed=True,
    )
