"""Answer parsing helpers (contact line, links, handles).

Kept separate from the handlers so the heuristics are unit-testable and the
handlers stay boring.
"""

from __future__ import annotations

import re

from app.utils.text import clean_text

__all__ = ["normalize_handle", "normalize_website", "parse_contact_line", "split_links"]

#: separators people actually use between name and position.  A bare "-" between
#: letters is deliberately not a separator, so "Anne-Marie" survives.
_SEPARATORS = re.compile(r"\s*[—–]\s*|\s+[-|]{1,2}\s+|\s*[:,;]\s*|\s+/\s+")

#: words that almost certainly begin a job title in uz/ru/en
_POSITION_HINTS = re.compile(
    r"\b("
    r"direktor|direktori|menejer|menejeri|rahbar|boshliq|mudir|mudiri|operator|admin|"
    r"asistent|buhalg|marketolog|sotuvchi|yetakchi|bosh|savdo|logist|founder|owner|"
    r"ceo|cto|cfo|director|manager|head|lead|specialist|sales|chef|buyer|diler"
    r"|директор|менеджер|руководитель|заместитель|специалист|маркетолог|продаж| "
    r"начальник|основатель|владелец|шеф|закупщик|логист|head of"
    r")\b",
    re.IGNORECASE,
)

_URL_LIKE = re.compile(r"^(https?://)?([\w-]+\.)+[a-z]{2,}(/\S*)?$", re.IGNORECASE)
_INSTAGRAM_HOST = re.compile(r"(^|\.)(instagram\.com|instagr\.am)$", re.IGNORECASE)


def parse_contact_line(raw: str | None) -> tuple[str, str | None]:
    """Split ``"Azizbek — Savdo direktori"`` into ``("Azizbek", "Savdo direktori")``.

    When the split is uncertain we return the whole line as the contact name and
    ``None`` as position - the raw value is never lost (spec requirement).
    """
    text = clean_text(raw, max_len=160)
    if not text:
        return "", None

    parts = [part.strip(" \t.,;:") for part in _SEPARATORS.split(text) if part.strip(" \t.,;:")]
    if len(parts) >= 2:
        return parts[0][:120], clean_text(" ".join(parts[1:]), max_len=120) or None
    if len(parts) == 1:
        text = parts[0]

    match = _POSITION_HINTS.search(text)
    if match and match.start() > 0:
        name = text[: match.start()].strip(" \t.,;:-—–/")
        position = text[match.start() :].strip(" \t.,;:-—–/")
        if name and position:
            return name[:120], position[:120]

    return text[:120], None


def normalize_handle(raw: str | None) -> str | None:
    """``@company`` / ``https://instagram.com/company`` -> ``@company``."""
    text = clean_text(raw, max_len=120)
    if not text:
        return None
    text = text.strip().rstrip("/")
    match = re.search(r"(?:instagram\.com|instagr\.am)/(@?[\w.]+)", text, re.IGNORECASE)
    if match:
        text = match.group(1)
    text = text.lstrip("@")
    text = re.sub(r"[^\w.]", "", text)
    return f"@{text}" if text else None


def normalize_website(raw: str | None) -> str | None:
    """Trim a URL down to a compact, clickable domain+path."""
    text = clean_text(raw, max_len=200)
    if not text:
        return None
    text = text.strip().rstrip("/")
    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    if _INSTAGRAM_HOST.search(text.split("/", 1)[0]):
        # an instagram link in the website slot: normalise as a handle instead
        handle = normalize_handle(text)
        return text if handle is None else handle
    if " " in text or not text:
        return None
    return text[:200]


def split_links(raw: str | None) -> tuple[str | None, str | None]:
    """Split the URL answer into ``(website, instagram)``.

    Accepts several formats in one message:

    * ``foodcompany.uz``                          -> website
    * ``@foodcompany``                            -> instagram
    * ``sayt: foodcompany.uz\\ninstagram: @sf``     -> both

    Anything that does not look like a domain (needs a dot) or a handle (needs ``@``)
    is rejected, so junk answers never reach the lead card.
    """
    website: str | None = None
    instagram: str | None = None

    for chunk in re.split(r"[\n,;]+|https?://", raw or ""):
        piece = chunk.strip()
        if not piece:
            continue

        instagram_labeled = re.match(r"^(instagram|ig|инста)\s*[:=-]\s*", piece, re.IGNORECASE)
        if instagram_labeled:
            handle = normalize_handle(piece[instagram_labeled.end() :])
            instagram = instagram or handle
            continue

        website_labeled = re.match(r"^(sayt|сайт|site|web|veb)\s*[:=-]\s*", piece, re.IGNORECASE)
        if website_labeled:
            url = normalize_website(piece[website_labeled.end() :])
            if url and ("." in url or "/" in url):
                website = website or url
            continue

        if re.match(r"^@[\w.]{2,}$", piece):
            instagram = instagram or normalize_handle(piece)
            continue

        host = re.sub(r"^https?://", "", piece, flags=re.IGNORECASE).split("/", 1)[0]
        if _INSTAGRAM_HOST.search(host):
            instagram = instagram or (normalize_handle(piece) or piece)
            continue

        url = normalize_website(piece)
        if url and ("." in url or "/" in url):
            website = website or url

    if instagram is None and website is None:
        # last chance: a bare domain typed with nothing else in the message
        fallback = normalize_website(raw)
        if fallback and "." in fallback:
            website = fallback
    return website, instagram
