"""Telegram Ads attribution.

Ads campaigns point at deep links such as ``t.me/foodera_bot?start=tgads_foodera_uz_01``.
The payload is parsed into ``source / campaign / creative`` and *always* kept raw,
so a payload we cannot parse still lands in the database and in the sales card.

Grammar (first separator wins: ``_``, ``-``, ``~``, ``:``)::

    <source>_<campaign>_<creative...>

Examples::

    tgads_foodera_uz_01        -> source=telegram_ads campaign=foodera creative=uz_01
    tgads_foodera_video01      -> source=telegram_ads campaign=foodera creative=video01
    tgads_foodera_distributor  -> source=telegram_ads campaign=foodera creative=distributor
    channel_kiss_foodera       -> source=telegram_channel campaign=kiss creative=foodera
    foodera                    -> source=unknown       campaign=None creative=None raw kept
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["MAX_PAYLOAD_LENGTH", "SOURCE_LABELS", "SourceInfo", "parse_start_payload"]

MAX_PAYLOAD_LENGTH = 120
_SAFE_TOKEN = re.compile(r"^[a-z0-9]{1,40}$")
_SEPARATORS = re.compile(r"[_\-~:]")
_LANGUAGE_TOKENS = {
    "uz": "uz",
    "uzb": "uz",
    "lat": "uz",
    "uzbek": "uz",
    "samarqand": None,
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "cyr": None,
}

#: canonical source value -> label used in the sales-group lead card
SOURCE_LABELS: dict[str, str] = {
    "telegram_ads": "Telegram Ads",
    "telegram_channel": "Telegram channel",
    "telegram_post": "Telegram post",
    "qr": "QR / offline",
    "flyer": "Flyer / offline",
    "partner": "Partner",
    "website": "Website",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "direct": "Direct",
    "unknown": "Unknown",
}

#: first-token aliases we recognise as sources (Telegram ads links commonly use ``tgads``/``tds``)
SOURCE_ALIASES: dict[str, str] = {
    "tgads": "telegram_ads",
    "tgadsbot": "telegram_ads",
    "tds": "telegram_ads",
    "ads": "telegram_ads",
    "telegramads": "telegram_ads",
    "tg": "telegram_channel",
    "tme": "telegram_channel",
    "channel": "telegram_channel",
    "post": "telegram_post",
    "qr": "qr",
    "qr2026": "qr",
    "flyer": "flyer",
    "offline": "flyer",
    "partner": "partner",
    "site": "website",
    "web": "website",
    "instagram": "instagram",
    "ig": "instagram",
    "facebook": "facebook",
    "fb": "facebook",
}


@dataclass(frozen=True)
class SourceInfo:
    """Parsed ``/start`` payload (immutable value object)."""

    start_payload: str | None = None
    source: str = "direct"
    campaign: str | None = None
    creative: str | None = None
    language_hint: str | None = None
    parsed: bool = True

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source.replace("_", " ").title())

    @property
    def is_paid_ads(self) -> bool:
        return self.source == "telegram_ads"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "start_payload": self.start_payload,
            "source": self.source,
            "campaign": self.campaign,
            "creative": self.creative,
        }


def _sanitize(token: str) -> str | None:
    """Lowercase + strict character whitelist; ``None`` when the token is junk."""
    token = token.strip().lower().lstrip("/")
    if not token:
        return None
    if _SAFE_TOKEN.match(token):
        return token
    # tolerate dots in domains (site_foodcompany_uz) and drop the rest
    cleaned = re.sub(r"[^a-z0-9]", "", token)
    return cleaned or None


def _language_hint(tokens: list[str]) -> str | None:
    for token in tokens:
        hint = _LANGUAGE_TOKENS.get(token)
        if hint:
            return hint
    return None


def parse_start_payload(raw: str | None) -> SourceInfo:
    """Parse a ``/start`` payload, never raising.

    Unparsable payloads keep ``source="unknown"`` and the raw string, exactly as the
    qualification spec requires.
    """
    if raw is None:
        return SourceInfo(start_payload=None, source="direct", parsed=False)

    original = str(raw).strip()[: MAX_PAYLOAD_LENGTH * 2]
    if not original:
        return SourceInfo(start_payload=None, source="direct", parsed=False)

    cleaned = re.sub(r"[^0-9A-Za-z_\-~:.]", "", original)
    truncated = cleaned[:MAX_PAYLOAD_LENGTH]

    tokens = [token for token in _SEPARATORS.split(truncated) if token]
    sanitized = [safe for safe in (_sanitize(token) for token in tokens) if safe]

    if not sanitized:
        return SourceInfo(
            start_payload=original[:MAX_PAYLOAD_LENGTH], source="unknown", parsed=False
        )

    language_hint = _language_hint(sanitized)
    head = sanitized[0]

    if head in SOURCE_ALIASES:
        source = SOURCE_ALIASES[head]
        rest = sanitized[1:]
    elif len(sanitized) == 1:
        # e.g. "foodera" or "promo2026" - we keep it, but cannot classify the source
        return SourceInfo(
            start_payload=original[:MAX_PAYLOAD_LENGTH],
            source="unknown",
            campaign=truncated,
            creative=None,
            language_hint=language_hint,
            parsed=False,
        )
    else:
        source = "unknown"
        rest = sanitized[1:]

    campaign = rest[0] if rest else None
    creative = "_".join(rest[1:]) if len(rest) > 1 else None

    return SourceInfo(
        start_payload=original[:MAX_PAYLOAD_LENGTH],
        source=source,
        campaign=campaign,
        creative=creative,
        language_hint=language_hint,
        parsed=True,
    )
