"""Visitor badge (``MEHMON BEYDJIGI``): the picture a guest shows at the entrance.

The badge is **drawn from scratch** with Pillow - no template file, no assets on disk -
so it can be regenerated any time and shipped as a single PNG in memory:

* ``generate_badge(lead, lang)``  - pure function, returns the PNG bytes (no Telegram);
* :func:`send_badge`             - thin delivery helper around ``send_photo``;
* :func:`badge_caption`          - the caption that goes with the picture.

Nothing here is stateful or persisted: the badge is redrawn from the lead row on every
request (``/beydjik``, the admin panel download, the end of the visitor funnel), which is
why the feature needs no database migration at all.

Failure policy: rendering and delivery must **never** break the registration flow.  A
missing font, a missing field or a Telegram hiccup only produces a log line (and
``False`` as the return value of :func:`send_badge`).
"""

from __future__ import annotations

import io
import logging
from typing import Any

import qrcode
from aiogram.types import BufferedInputFile
from app.database.models import Lead, LeadType
from app.i18n import normalize_language, option_label, t
from app.options import Intent, Region
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_M

__all__ = [
    "BADGE_HEIGHT",
    "BADGE_WIDTH",
    "QR_LEFT",
    "QR_SIZE",
    "QR_TOP",
    "badge_caption",
    "badge_filename",
    "badge_qr_text",
    "generate_badge",
    "is_visitor_lead",
    "maybe_send_badge",
    "send_badge",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------- canvas
BADGE_WIDTH = 900
BADGE_HEIGHT = 1200

BACKGROUND = "#ffffff"
INK = "#111827"  # header block / headline text
MUTED = "#4b5563"  # region line
FAINT = "#9ca3af"  # the "show this badge" footnote
HEADER_SUB = "#d1d5db"  # date + venue line inside the dark header
BAND_BG = "#1d4ed8"  # the blue "MEHMON" ribbon
BAND_TEXT = "#ffffff"
OUTLINE = "#e5e7eb"

QR_SIZE = 340
QR_BORDER = 4  # quiet zone in modules - scanners need it
QR_INSET = 10  # white frame around the QR block
QR_LEFT = (BADGE_WIDTH - QR_SIZE) // 2
QR_TOP = 706

#: vertical anchor of every block of the card, top to bottom
HEADER_HEIGHT = 240
HEADER_TITLE_Y = 92
HEADER_SUB_Y = 178
BAND_TOP = 300
BAND_BOTTOM = 440
BAND_TEXT_Y = 370
NAME_Y = 550
REGION_Y = 676
CODE_Y = 1084
HINT_Y = 1146

NAME_MAX_WIDTH = 760
NAME_MAX_SIZE = 78
NAME_MIN_SIZE = 34
NAME_MAX_LINES = 2

#: ``fonts-dejavu-core`` (installed in the Dockerfile) - the only font we rely on.
BOLD_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)
REGULAR_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)

_font_cache: dict[tuple[bool, int], Any] = {}


# ----------------------------------------------------------------------------- fonts
def _load_font(size: int, *, bold: bool = False) -> Any:
    """DejaVu at ``size`` px, or PIL's built-in bitmap font when it is not installed.

    A slim image without ``fonts-dejavu-core`` must degrade (ugly but readable) instead of
    crashing the registration flow.
    """
    cached = _font_cache.get((bold, size))
    if cached is not None:
        return cached

    font: Any = None
    for path in BOLD_FONT_PATHS if bold else REGULAR_FONT_PATHS:
        try:
            font = ImageFont.truetype(path, size)
            break
        except (OSError, ValueError):  # font not shipped on this host
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)  # Pillow >= 10.1
        except Exception:  # pragma: no cover - very old Pillow
            font = ImageFont.load_default()

    _font_cache[(bold, size)] = font
    return font


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> float:
    try:
        return float(draw.textlength(text, font=font))
    except Exception:  # pragma: no cover - exotic font object
        size = float(getattr(font, "size", 0) or 0)
        return len(text) * (size * 0.6 or 6.0)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: float) -> str:
    """Cut ``text`` to ``max_width`` with an ellipsis - used only when nothing else fits."""
    if _text_width(draw, text, font) <= max_width:
        return text
    for end in range(len(text) - 1, 0, -1):
        candidate = f"{text[:end].rstrip()}…"
        if _text_width(draw, candidate, font) <= max_width:
            return candidate
    return "…"


def _wrap(text: str, max_lines: int) -> list[str]:
    """Greedy word wrap into at most ``max_lines`` lines (single words are never split)."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(lines) == max_lines - 1:
            current = f"{current} {word}"
            continue
        lines.append(current)
        current = word
    lines.append(current)
    return lines[:max_lines]


def _fit_name(draw: ImageDraw.ImageDraw, name: str) -> tuple[list[str], Any]:
    """Biggest bold font for which the name fits in one or two lines of the card."""
    for size in range(NAME_MAX_SIZE, NAME_MIN_SIZE - 1, -2):
        font = _load_font(size, bold=True)
        if _text_width(draw, name, font) <= NAME_MAX_WIDTH:
            return [name], font
        lines = _wrap(name, NAME_MAX_LINES)
        if len(lines) > 1 and all(
            _text_width(draw, line, font) <= NAME_MAX_WIDTH for line in lines
        ):
            return lines, font

    # Extremely long (or extremely wordy) name: shrink to the floor, wrap and clip.
    font = _load_font(NAME_MIN_SIZE, bold=True)
    lines = [
        _ellipsize(draw, line, font, NAME_MAX_WIDTH)
        for line in _wrap(name, NAME_MAX_LINES)[:NAME_MAX_LINES]
    ]
    return lines or [""], font


# ------------------------------------------------------------------------ lead fields
def is_visitor_lead(lead: Lead) -> bool:
    """True for guest registrations only - exhibitors and partners never get a badge."""
    if str(getattr(lead, "lead_type", "") or "") == LeadType.VISITOR.value:
        return True
    return str(getattr(lead, "intent", "") or "") == Intent.VISITOR.value


def badge_qr_text(lead: Lead) -> str:
    """The exact string encoded into the QR code (the lead code, e.g. ``FD000123``)."""
    code = str(getattr(lead, "lead_code", "") or "").strip()
    return code or str(getattr(lead, "telegram_user_id", "") or "")


def badge_filename(lead: Lead) -> str:
    """Download name of the PNG (also the filename Telegram shows)."""
    return f"{badge_qr_text(lead) or 'foodera'}_badge.png"


def badge_caption(lang: str = "uz") -> str:
    """Caption shown next to the badge photo (i18n ``badge.caption``)."""
    return t("badge.caption", normalize_language(lang))


def _guest_name(lead: Lead) -> str:
    """Guest name for the badge: the typed answer first, then the Telegram profile."""
    typed = str(getattr(lead, "contact_name", "") or "").strip()
    if typed:
        return typed
    full = " ".join(
        part.strip()
        for part in (
            getattr(lead, "telegram_first_name", None),
            getattr(lead, "telegram_last_name", None),
        )
        if part and str(part).strip()
    )
    if full:
        return full
    username = str(getattr(lead, "telegram_username", "") or "").strip()
    if username:
        return f"@{username.lstrip('@')}"
    return "—"


def _region_text(lead: Lead, lang: str) -> str:
    """Region label from the i18n catalog; the country is appended when it was asked."""
    region = str(getattr(lead, "region", "") or "")
    country = str(getattr(lead, "country", "") or "").strip()
    if not region and country:
        return country
    label = option_label("region", region or None, lang)
    if country and region == Region.FOREIGN.value:
        return country
    if country and region == Region.OTHER_REGION.value:
        return f"{label} · {country}"
    return label


# ---------------------------------------------------------------------------- drawing
def _draw_header(draw: ImageDraw.ImageDraw, lang: str) -> None:
    draw.rectangle((0, 0, BADGE_WIDTH, HEADER_HEIGHT), fill=INK)
    draw.text(
        (BADGE_WIDTH / 2, HEADER_TITLE_Y),
        t("badge.event_title", lang),
        font=_load_font(60, bold=True),
        fill=BACKGROUND,
        anchor="mm",
    )
    draw.text(
        (BADGE_WIDTH / 2, HEADER_SUB_Y),
        t("badge.event_line", lang),
        font=_load_font(32),
        fill=HEADER_SUB,
        anchor="mm",
    )


def _draw_band(draw: ImageDraw.ImageDraw, lang: str) -> None:
    """The blue ribbon with ``MEHMON`` / ``ГОСТЬ``."""
    draw.rounded_rectangle((70, BAND_TOP, BADGE_WIDTH - 70, BAND_BOTTOM), radius=26, fill=BAND_BG)
    draw.text(
        (BADGE_WIDTH / 2, BAND_TEXT_Y),
        t("badge.visitor_label", lang),
        font=_load_font(70, bold=True),
        fill=BAND_TEXT,
        anchor="mm",
    )


def _draw_name(draw: ImageDraw.ImageDraw, name: str) -> None:
    lines, font = _fit_name(draw, name)
    line_height = int(getattr(font, "size", 48) * 1.2)
    center_y = NAME_Y
    if len(lines) == 1:
        draw.text((BADGE_WIDTH / 2, center_y), lines[0], font=font, fill=INK, anchor="mm")
        return
    top = center_y - line_height // 2
    for index, line in enumerate(lines):
        draw.text(
            (BADGE_WIDTH / 2, top + index * line_height), line, font=font, fill=INK, anchor="mm"
        )


def _qr_tile(payload: str) -> Image.Image:
    """A crisp white QR tile: module size is chosen so the code never has to be scaled."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=QR_BORDER)
    qr.add_data(payload)
    qr.make(fit=True)

    modules = int(qr.modules_count) + 2 * QR_BORDER
    available = QR_SIZE - 2 * QR_INSET
    qr.box_size = max(1, available // modules)

    rendered = qr.make_image(fill_color=INK, back_color=BACKGROUND).convert("RGB")
    tile = Image.new("RGB", (QR_SIZE, QR_SIZE), BACKGROUND)
    if rendered.width > QR_SIZE or rendered.height > QR_SIZE:  # pragma: no cover - huge payload
        rendered = rendered.resize((QR_SIZE, QR_SIZE), Image.NEAREST)
    tile.paste(rendered, ((QR_SIZE - rendered.width) // 2, (QR_SIZE - rendered.height) // 2))
    return tile


def generate_badge(lead: Lead, lang: str = "uz") -> bytes:
    """Draw the guest badge for ``lead``; returns the PNG file as bytes.

    Pure picture generation - no Telegram, no database, no files on disk - so the design
    can be unit-tested (signature, size, QR payload) in milliseconds.
    """
    language = normalize_language(lang)
    canvas = Image.new("RGB", (BADGE_WIDTH, BADGE_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    _draw_header(draw, language)
    _draw_band(draw, language)
    _draw_name(draw, _guest_name(lead))
    draw.text(
        (BADGE_WIDTH / 2, REGION_Y),
        _region_text(lead, language),
        font=_load_font(34),
        fill=MUTED,
        anchor="mm",
    )

    canvas.paste(_qr_tile(badge_qr_text(lead)), (QR_LEFT, QR_TOP))
    draw.rectangle(
        (QR_LEFT, QR_TOP, QR_LEFT + QR_SIZE, QR_TOP + QR_SIZE),
        outline=OUTLINE,
        width=2,
    )

    draw.text(
        (BADGE_WIDTH / 2, CODE_Y),
        badge_qr_text(lead),
        font=_load_font(46, bold=True),
        fill=INK,
        anchor="mm",
    )
    draw.text(
        (BADGE_WIDTH / 2, HINT_Y),
        t("badge.hint", language),
        font=_load_font(26),
        fill=FAINT,
        anchor="mm",
    )
    draw.rectangle((0, 0, BADGE_WIDTH - 1, BADGE_HEIGHT - 1), outline=OUTLINE, width=4)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# --------------------------------------------------------------------------- delivery
async def send_badge(
    bot: Any,
    lead: Lead,
    *,
    lang: str = "uz",
    chat_id: int | None = None,
    caption: str | None = None,
) -> bool:
    """Send the badge as a photo; ``True`` when it reached the chat.

    Every failure (rendering *and* delivery) is swallowed and logged here: the caller is
    a registration flow, and a guest must still finish signing up when Telegram or
    Pillow misbehave.
    """
    if bot is None:  # pragma: no cover - dry runs / tests without a bot
        return False

    language = normalize_language(lang)
    try:
        image = generate_badge(lead, language)
    except Exception:
        logger.exception("could not render the visitor badge for lead %s", _code_of(lead))
        return False

    try:
        await bot.send_photo(
            chat_id=chat_id if chat_id is not None else lead.telegram_user_id,
            photo=BufferedInputFile(image, filename=badge_filename(lead)),
            caption=caption or badge_caption(language),
        )
        return True
    except Exception:
        # unhandled: the user blocked the bot, Telegram is down, the chat is gone - the
        # registration itself is already stored and must not be rolled back
        logger.exception("could not deliver the visitor badge for lead %s", _code_of(lead))
        return False


async def maybe_send_badge(
    bot: Any,
    lead: Lead,
    *,
    lang: str = "uz",
    enabled: bool = True,
    chat_id: int | None = None,
) -> bool:
    """Send the badge only when the feature is on **and** the lead is a guest.

    The single decision point shared by the end of the visitor funnel and the
    ``/beydjik`` command, so "exhibitors never receive a badge" is enforced in one place.
    """
    if not enabled:
        return False
    if not is_visitor_lead(lead):
        logger.debug("badge skipped: lead %s is not a visitor", _code_of(lead))
        return False
    return await send_badge(bot, lead, lang=lang, chat_id=chat_id)


def _code_of(lead: Any) -> str:
    return str(getattr(lead, "lead_code", None) or getattr(lead, "id", "?"))
