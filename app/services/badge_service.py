"""Visitor badge (``MEHMON BEYDJIGI``): the FOODERA guest card the visitor shows at the door.

The card is **drawn from scratch** with Pillow - no template file, no database column - so it
can be regenerated at any time and shipped as a single PNG in memory:

* :func:`generate_badge`      - pure function, returns the PNG bytes (no Telegram);
* :func:`send_badge`          - thin delivery helper around ``send_photo``;
* :func:`maybe_send_badge`    - the one place that decides *who* gets a badge;
* :func:`badge_caption` / :func:`badge_filename` - caption and download name.

Brand design (see ``app/assets/brand/README.md`` for the palette and the logo slot):

* cream card (900x1200) with a full-card vine pattern, a 2 px gold frame and a fine gold rule;
* deep-azure header with diagonal stripes, gold vine branches and the round FOODERA emblem
  (white disc, gold ring, two overlapping eight-pointed stars, ``FOODERA`` / ``EXPO 2026``);
  when the organisers drop an official logo into ``app/assets/brand/`` it replaces the emblem;
* azure ribbon with ``MEHMON`` / ``ГОСТЬ`` (74 px), the guest name, a gold star divider and a
  sand region pill with a blue map pin;
* a white QR *talon* - perforated, with blue scanner brackets - carrying the lead code in a
  letter-spaced headline.  Same 900x1200 canvas and the same QR payload as before.

Nothing here is stateful or persisted: the badge is redrawn from the lead row on every request
(``/beydjik``, the admin panel download, the end of the visitor funnel), which is why the
feature needs no database migration at all.

Failure policy: rendering and delivery must **never** break the registration flow.  A missing
font, a missing field, a broken logo file or a Telegram hiccup only produces a log line (and
``False`` as the return value of :func:`send_badge`).
"""

from __future__ import annotations

import io
import logging
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import qrcode
from aiogram.types import BufferedInputFile
from app.database.models import Lead, LeadType
from app.i18n import normalize_language, option_label, t
from app.options import Intent, Region
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont
from qrcode.constants import ERROR_CORRECT_M

__all__ = [
    "BADGE_HEIGHT",
    "BADGE_WIDTH",
    "CARD_BOTTOM",
    "CARD_LEFT",
    "CARD_RIGHT",
    "CARD_TOP",
    "QR_SIZE",
    "QR_TOP",
    "badge_caption",
    "badge_filename",
    "badge_qr_text",
    "clear_font_cache",
    "generate_badge",
    "is_visitor_lead",
    "maybe_send_badge",
    "resolve_font_path",
    "resolve_logo_path",
    "send_badge",
]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- brand palette
#: official FOODERA EXPO 2026 colours - ``app/assets/brand/README.md`` documents every one
PAPER = "#FFFFFF"
CREAM = "#FAF6EE"
CREAM_DEEP = "#EEE7D9"
INK = "#0C283C"
AZURE_DARK = "#0C3E60"
AZURE = "#2A8FC7"
AZURE_DEEP = "#126091"
GOLD = "#C9A96A"
GOLD_DEEP = "#A6884F"
SAND = "#F2EBDE"
MUTED = "#5A6976"
FAINT = "#96A0AA"

#: name -> hex, so the palette can be iterated over (docs, tests, the brand README)
PALETTE: dict[str, str] = {
    "PAPER": PAPER,
    "CREAM": CREAM,
    "CREAM_DEEP": CREAM_DEEP,
    "INK": INK,
    "AZURE_DARK": AZURE_DARK,
    "AZURE": AZURE,
    "AZURE_DEEP": AZURE_DEEP,
    "GOLD": GOLD,
    "GOLD_DEEP": GOLD_DEEP,
    "SAND": SAND,
    "MUTED": MUTED,
    "FAINT": FAINT,
}

# ------------------------------------------------------------------------------- canvas
BADGE_WIDTH = 900
BADGE_HEIGHT = 1200

CARD_MARGIN = 18
CARD_RADIUS = 30
CARD_X0 = CARD_MARGIN
CARD_Y0 = CARD_MARGIN
CARD_X1 = BADGE_WIDTH - CARD_MARGIN - 1  # 881 - last pixel of the card
CARD_Y1 = BADGE_HEIGHT - CARD_MARGIN - 1  # 1181
CARD_BORDER = 2  # the gold frame around the whole card

HEADER_HEIGHT = 318
HEADER_TOP = CARD_Y0  # 18
HEADER_BOTTOM = HEADER_TOP + HEADER_HEIGHT  # 336
ACCENT_BAR = 12  # the gold rule right under the header
RULE_BOTTOM = HEADER_BOTTOM + ACCENT_BAR  # 348

#: the round FOODERA emblem, centred in the header
COIN_SIZE = 232
COIN_LEFT = (BADGE_WIDTH - COIN_SIZE) // 2  # 334
COIN_TOP = 26
COIN_RING = 8
COIN_ANNULUS = (0.18, 0.82)  # the vine pattern band inside the ring
COIN_STAR_RADIUS = 46
COIN_STAR_OFFSET = 13
COIN_STAR_ROW = 0.33  # vertical centre of the stars, in coin radii
COIN_SHADOW_DROP = 20
DATE_Y = 288
DATE_SIZE = 27
TAGLINE_Y = 316
TAGLINE_SIZE = 15

BAND_TOP = 372
BAND_BOTTOM = 498
BAND_TEXT_Y = (BAND_TOP + BAND_BOTTOM) // 2  # 435
BAND_TEXT_SIZE = 74

NAME_Y = 551
NAME_MAX_WIDTH = 760
NAME_MAX_SIZE = 74  # one line
NAME_TWO_LINE_SIZE = 52  # two lines
NAME_MIN_SIZE = 30  # floor before the ellipsis takes over
NAME_LINE_HEIGHT = 1.14

DIVIDER_Y = 636
DIVIDER_STAR = 40
DIVIDER_GAP = 62  # half-width of the hole the star sits in

REGION_Y = 692
REGION_PILL_HEIGHT = 48
REGION_PILL_MAX_WIDTH = 700
REGION_PIN = 26
REGION_TEXT_MAX_SIZE = 32
REGION_TEXT_MIN_SIZE = 20
REGION_TEXT_MAX_WIDTH = 520

#: the white QR talon (a tear-off ticket)
CARD_LEFT = 250
CARD_RIGHT = 650
CARD_TOP = 730
CARD_BOTTOM = 1112
CARD_INNER_RADIUS = 26
CARD_BRACKET = 52

QR_SIZE = 300
QR_BORDER = 4  # quiet zone in modules - scanners need it
QR_INSET = 8  # white frame around the QR block inside the talon
QR_LEFT = (BADGE_WIDTH - QR_SIZE) // 2  # 300
QR_TOP = 744

TICKET_DIVIDER_Y = 1058  # perforation with the gold diamond
TICKET_NOTCH = 13
CODE_Y = 1088
CODE_SIZE = 42
CODE_LETTER_SPACING = 3.0
HINT_Y = 1152
HINT_SIZE = 26

PATTERN_CELL = 96  # vine pattern tile
PATTERN_ALPHA = 150
WATERMARK_ALPHA = 26
WATERMARK_Y = 590
DECOR_VINE_LENGTH = 272
DECOR_VINE_ALPHA = 60
DECOR_VINE_ANGLE = 10
DECOR_VINE_X = (120, BADGE_WIDTH - 120)
DECOR_VINE_Y = (CARD_TOP + CARD_BOTTOM) // 2  # 921 - beside the talon

LOGO_MAX_WIDTH = 560
LOGO_MAX_HEIGHT = 260

# -------------------------------------------------------------------------------- fonts
#: ``fonts-dejavu-core`` (installed in the Dockerfile) is the first link of the chain; the
#: system fonts behind it only have to be able to print ``ГОСТЬ``.
BOLD_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
REGULAR_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

#: what a fallback font has to be able to print (the Russian ribbon label)
CYRILLIC_PROBE = "ГОСТЬ"

_font_cache: dict[tuple[bool, int], Any] = {}
_font_paths: dict[bool, str | None] = {}
_mask_cache: dict[tuple[str, tuple[int, int], int], Image.Image] = {}


def _usable(path: str | Path) -> bool:
    """True when ``path`` exists **and** Pillow can really open it as a font."""
    try:
        if not Path(path).is_file():
            return False
        ImageFont.truetype(str(path), 16)
    except (OSError, ValueError):  # not a font / unreadable file
        return False
    return True


def _renders_cyrillic(path: str | Path, *, size: int = 32) -> bool:
    """True when the font has real glyphs for ``ГОСТЬ`` (no tofu boxes on the badge)."""
    try:
        font = ImageFont.truetype(str(path), size)
        if font.getmask(CYRILLIC_PROBE, mode="L").getbbox() is None:  # nothing painted at all
            return False
        advances = {round(font.getlength(char), 3) for char in CYRILLIC_PROBE}
    except (OSError, ValueError):  # pragma: no cover - already guarded by _usable()
        return False
    return len(advances) > 1


def resolve_font_path(*, bold: bool = False) -> str | None:
    """First font of the chain that can print the badge, or ``None`` for PIL's built-in font.

    The chain is ``fonts-dejavu-core`` -> the system fonts of the host (only when they really
    cover Cyrillic, because ``ГОСТЬ`` is painted on every Russian badge) -> ``None``.
    """
    if bold in _font_paths:
        return _font_paths[bold]

    resolved: str | None = None
    for candidate in BOLD_FONT_PATHS if bold else REGULAR_FONT_PATHS:
        if _usable(candidate) and _renders_cyrillic(candidate):
            resolved = candidate
            break

    if resolved is None:
        logger.warning("no font with Cyrillic support found - falling back to PIL's default font")
    _font_paths[bold] = resolved
    return resolved


def clear_font_cache() -> None:
    """Forget every resolved path and loaded font (tests, or a host that just gained fonts)."""
    _font_cache.clear()
    _font_paths.clear()


def _load_font(size: int, *, bold: bool = False) -> Any:
    """Chain font at ``size`` px, or PIL's built-in bitmap font when nothing else is usable.

    A slim image without ``fonts-dejavu-core`` must degrade (ugly but readable) instead of
    crashing the registration flow.
    """
    cached = _font_cache.get((bold, size))
    if cached is not None:
        return cached

    font: Any = None
    path = resolve_font_path(bold=bold)
    if path is not None:
        try:
            font = ImageFont.truetype(path, size)
        except (OSError, ValueError):  # pragma: no cover - the path loaded a moment ago
            font = None
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


def _split_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: Any,
    max_width: float,
) -> list[str]:
    """Break the name over (at most) two lines, both fitting whenever that is possible.

    Words are never cut here; the caller decides whether the leftover gets an ellipsis.
    """
    words = text.split()
    if len(words) <= 1:
        return [text]

    best: list[str] = [text]
    best_score: tuple[float, float] | None = None
    for index in range(1, len(words)):
        first = " ".join(words[:index])
        width_first = _text_width(draw, first, font)
        if width_first > max_width:
            break
        second = " ".join(words[index:])
        width_second = _text_width(draw, second, font)
        score = (0.0 if width_second <= max_width else 1.0, max(width_first, width_second))
        if best_score is None or score < best_score:
            best, best_score = [first, second], score
    return best


def _fit_name(draw: ImageDraw.ImageDraw, name: str) -> tuple[list[str], Any]:
    """Largest bold size for the name: one line (<= 74 px), two lines (<= 52 px), then ellipsis."""
    text = name.strip()
    for size in range(NAME_MAX_SIZE, NAME_TWO_LINE_SIZE - 1, -2):
        font = _load_font(size, bold=True)
        if _text_width(draw, text, font) <= NAME_MAX_WIDTH:
            return [text], font

    lines: list[str] = [text]
    for size in range(NAME_TWO_LINE_SIZE, NAME_MIN_SIZE - 1, -2):
        font = _load_font(size, bold=True)
        lines = _split_lines(draw, text, font, NAME_MAX_WIDTH)
        if len(lines) > 1 and all(
            _text_width(draw, line, font) <= NAME_MAX_WIDTH for line in lines
        ):
            return lines, font

    font = _load_font(NAME_MIN_SIZE, bold=True)
    lines = _split_lines(draw, text, font, NAME_MAX_WIDTH)
    return [_ellipsize(draw, line, font, NAME_MAX_WIDTH) for line in lines], font


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_size: int,
    min_size: int,
    max_width: float,
    bold: bool = False,
) -> Any:
    """Largest font whose ``text`` fits into ``max_width``, never smaller than ``min_size``."""
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(size, bold=bold)
        if _text_width(draw, text, font) <= max_width:
            return font
    return _load_font(min_size, bold=bold)


def _draw_spaced(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: Any,
    fill: Any,
    *,
    spacing: float,
) -> None:
    """Draw letter-spaced text centred on ``xy`` (Pillow has no tracking of its own)."""
    widths = [_text_width(draw, char, font) for char in text]
    total = sum(widths) + spacing * max(0, len(text) - 1)
    x = xy[0] - total / 2
    for char, width in zip(text, widths, strict=True):
        draw.text((x + width / 2, xy[1]), char, font=font, fill=fill, anchor="mm")
        x += width + spacing


# -------------------------------------------------------------------------- brand assets
BRAND_DIR = Path(__file__).resolve().parents[1] / "assets" / "brand"
#: file names the logo slot looks for, in order (see ``app/assets/brand/README.md``)
LOGO_NAMES: tuple[str, ...] = (
    "logo.png",
    "logo.jpg",
    "logo.jpeg",
    "logo.webp",
    "foodera.png",
    "foodera-logo.png",
    "foodera_logo.png",
)


def resolve_logo_path() -> Path | None:
    """The official logo file in :data:`BRAND_DIR`, or ``None`` to draw the FOODERA emblem."""
    for name in LOGO_NAMES:
        candidate = BRAND_DIR / name
        if candidate.is_file():
            return candidate
    return None


def _logo_file(logo_path: str | Path | None) -> Path | None:
    """``logo_path`` wins; ``None`` means "look in the brand folder"; ``""`` disables the slot."""
    if logo_path is None:
        return resolve_logo_path()
    if isinstance(logo_path, str) and not logo_path.strip():
        return None
    path = Path(logo_path)
    return path if path.is_file() else None


def _load_logo(path: str | Path) -> Image.Image | None:
    """Open the logo and scale it into the slot (560x260, aspect kept); ``None`` when broken.

    A logo the organisers dropped in by mistake (a PDF renamed to ``.png``, a truncated
    download) must never take the funnel down - the drawn emblem is used instead.
    """
    try:
        with Image.open(path) as opened:
            logo = opened.convert("RGBA")
    except Exception:
        logger.warning("brand logo %s could not be read - drawing the emblem instead", path)
        return None

    ratio = min(LOGO_MAX_WIDTH / logo.width, LOGO_MAX_HEIGHT / logo.height, 1.0)
    if ratio < 1.0:
        logo = logo.resize(
            (max(1, round(logo.width * ratio)), max(1, round(logo.height * ratio))),
            Image.LANCZOS,
        )
    return logo


def _logo_position(logo: Image.Image) -> tuple[int, int]:
    """Where the official logo sits: horizontally centred, vertically centred on the emblem."""
    centre_y = COIN_TOP + COIN_SIZE / 2
    top = max(CARD_Y0 + 4, round(centre_y - logo.height / 2))
    return round((BADGE_WIDTH - logo.width) / 2), top


# --------------------------------------------------------------------------- lead fields
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


# -------------------------------------------------------------------------- paint helpers
def _rgb(color: str) -> tuple[int, int, int]:
    red, green, blue = ImageColor.getrgb(color)[:3]
    return int(red), int(green), int(blue)


def _rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (*_rgb(color), max(0, min(255, alpha)))


def _blend(color_a: str, color_b: str, ratio: float) -> str:
    """Mix two palette colours (``ratio`` 0 -> ``color_a``, 1 -> ``color_b``)."""
    first, second = _rgb(color_a), _rgb(color_b)
    return "#{:02X}{:02X}{:02X}".format(
        *(round(a + (b - a) * ratio) for a, b in zip(first, second, strict=True))
    )


def _solid(size: tuple[int, int], color: str, alpha: int = 255) -> Image.Image:
    return Image.new("RGBA", size, _rgba(color, alpha))


def _tint(mask: Image.Image, color: str, alpha: int = 255) -> Image.Image:
    """Turn a coverage mask (``L``) into a coloured RGBA layer."""
    if mask.mode != "L":
        mask = mask.convert("L")
    layer = _solid(mask.size, color)
    layer.putalpha(ImageChops.multiply(mask, Image.new("L", mask.size, alpha)))
    return layer


def _compose(
    base: Image.Image,
    layer: Image.Image,
    mask: Image.Image | None = None,
) -> Image.Image:
    """Alpha-composite ``layer`` over ``base``, optionally clipped by an ``L`` mask."""
    if mask is None:
        return Image.alpha_composite(base, layer)
    if mask.size != layer.size:
        mask = mask.resize(layer.size)
    clipped = layer.copy()
    if clipped.mode != "RGBA":
        clipped = clipped.convert("RGBA")
    clipped.putalpha(ImageChops.multiply(clipped.getchannel("A"), mask))
    return Image.alpha_composite(base, clipped)


def _rounded_mask(
    size: tuple[int, int],
    box: tuple[int, int, int, int],
    radius: int,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def _circle_mask(
    size: tuple[int, int],
    box: tuple[float, float, float, float],
    inner: float = 0.0,
) -> Image.Image:
    """Coverage of a disc (``inner=0``) or of an annulus from ``inner`` to the disc rim."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(box, fill=255)
    if inner > 0:
        centre_x = (box[0] + box[2]) / 2
        centre_y = (box[1] + box[3]) / 2
        radius = (box[2] - box[0]) / 2 * inner
        draw.ellipse(
            (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius),
            fill=0,
        )
    return mask


def _linear_gradient(
    size: tuple[int, int],
    start: str,
    end: str,
    *,
    direction: str = "vertical",
    alpha: int = 255,
) -> Image.Image:
    """A smooth gradient - computed at 1/8 scale, because gradients have no detail to lose."""
    width, height = size
    small_w = max(2, min(width, max(2, width // 8)))
    small_h = max(2, min(height, max(2, height // 8)))
    small = Image.new("RGBA", (small_w, small_h), _rgba(start, alpha))
    pixels = small.load()
    first, second = _rgb(start), _rgb(end)
    for y in range(small_h):
        row = y / (small_h - 1)
        for x in range(small_w):
            column = x / (small_w - 1)
            if direction == "horizontal":
                ratio = column
            elif direction == "diagonal":
                ratio = (column + row) / 2
            else:
                ratio = row
            pixels[x, y] = (
                round(first[0] + (second[0] - first[0]) * ratio),
                round(first[1] + (second[1] - first[1]) * ratio),
                round(first[2] + (second[2] - first[2]) * ratio),
                alpha,
            )
    if (small_w, small_h) != size:
        small = small.resize(size, Image.BICUBIC)
    return small


def _diagonal_stripes(
    size: tuple[int, int],
    color: str,
    *,
    alpha: int = 12,
    period: int = 42,
    width: int = 11,
) -> Image.Image:
    """Faint 45° stripes - the texture the header and the ribbon are built on."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if width <= 0 or period <= 0:
        return layer
    draw = ImageDraw.Draw(layer)
    fill = _rgba(color, alpha)
    image_w, image_h = size
    for x in range(-image_h - period, image_w + period, period):
        draw.line([(x, image_h), (x + image_h, 0)], fill=fill, width=width)
    return layer


def _alpha_ramp(width: int, height: int, stops: list[tuple[float, int]]) -> Image.Image:
    """A horizontal alpha ramp (used to let the divider lines fade out towards the frame)."""
    ramp = Image.new("L", (max(1, width), 1))
    pixels = ramp.load()
    for x in range(ramp.width):
        position = x / max(1, ramp.width - 1)
        pixels[x, 0] = _ramp_value(stops, position)
    return ramp.resize((max(1, width), max(1, height)), Image.BICUBIC)


def _ramp_value(stops: list[tuple[float, int]], position: float) -> int:
    if not stops:  # pragma: no cover - callers always pass stops
        return 0
    if position <= stops[0][0]:
        return stops[0][1]
    for (left_t, left_v), (right_t, right_v) in pairwise(stops):
        if position <= right_t:
            span = right_t - left_t
            ratio = 0.0 if span <= 0 else (position - left_t) / span
            return round(left_v + (right_v - left_v) * ratio)
    return stops[-1][1]


def _leaf_points(
    centre_x: float,
    centre_y: float,
    length: float,
    width: float,
    angle: float,
    *,
    steps: int = 12,
) -> list[tuple[float, float]]:
    """A pointed leaf (two mirrored arcs) rotated by ``angle`` degrees."""
    half_width = max(width, 1) / 2
    points: list[tuple[float, float]] = []
    for sign in (1, -1):
        for step in range(steps + 1):
            ratio = step / steps
            offset = math.sin(math.pi * ratio) ** 0.8 * half_width * sign
            along = (ratio - 0.5) * length
            points.append((offset, along))
    radians = math.radians(angle)
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    return [(centre_x + x * cos_a - y * sin_a, centre_y + x * sin_a + y * cos_a) for x, y in points]


def _star_points(
    centre_x: float,
    centre_y: float,
    radius: float,
    *,
    points: int = 8,
    inner_ratio: float = 0.44,
    rotation: float = -90.0,
) -> list[tuple[float, float]]:
    """An eight-pointed star: alternating outer vertices, 45° apart."""
    result: list[tuple[float, float]] = []
    for index in range(points * 2):
        distance = radius if index % 2 == 0 else radius * inner_ratio
        angle = math.radians(rotation + index * 180 / points)
        result.append(
            (centre_x + distance * math.cos(angle), centre_y + distance * math.sin(angle))
        )
    return result


def _draw_star(
    draw: ImageDraw.ImageDraw,
    centre_x: float,
    centre_y: float,
    radius: float,
    color: tuple[int, int, int, int],
    *,
    width: int = 3,
    filled: bool = False,
    inner_ratio: float = 0.44,
) -> None:
    points = _star_points(centre_x, centre_y, radius, inner_ratio=inner_ratio)
    if filled:
        draw.polygon(points, fill=color)
        return
    draw.line([*points, points[0]], fill=color, width=width, joint="curve")


def _vine_cell(cell: int = PATTERN_CELL) -> Image.Image:
    """One seamless tile of the vine pattern (spiral arcs + leaves), as an ``L`` mask."""
    key = ("cell", (cell, cell), cell)
    cached = _mask_cache.get(key)
    if cached is not None:
        return cached

    # The motif is drawn nine times on a 3x3 grid and cropped in the middle: every leaf that
    # crosses an edge reappears on the opposite side, so the tiles join without a seam.
    canvas = Image.new("L", (cell * 3, cell * 3), 0)
    draw = ImageDraw.Draw(canvas)
    for origin_y in (0, cell, cell * 2):
        for origin_x in (0, cell, cell * 2):
            _draw_cell_motif(draw, origin_x, origin_y, cell)

    tile = canvas.crop((cell, cell, cell * 2, cell * 2))
    _mask_cache[key] = tile
    return tile


def _draw_cell_motif(draw: ImageDraw.ImageDraw, origin_x: int, origin_y: int, cell: int) -> None:
    """The repeating content of one pattern cell: a wavy stem, five leaves and a spiral."""
    amplitude = cell * 0.22
    steps = 24
    stem = [
        (
            origin_x + step / steps * cell,
            origin_y + cell / 2 + amplitude * math.sin(2 * math.pi * step / steps),
        )
        for step in range(steps + 1)
    ]
    draw.line(stem, fill=255, width=2, joint="curve")

    for index in range(5):
        ratio = 0.12 + index * 0.19
        x = origin_x + ratio * cell
        y = origin_y + cell / 2 + amplitude * math.sin(2 * math.pi * ratio)
        slope = math.cos(2 * math.pi * ratio) * amplitude * 2 * math.pi / cell
        angle = math.degrees(math.atan(slope))
        side = 1 if index % 2 == 0 else -1
        draw.polygon(_leaf_points(x, y, cell * 0.26, cell * 0.13, angle + 62 * side), fill=255)

    spiral_x = origin_x + cell * 0.72
    spiral_y = origin_y + cell * 0.24
    draw.arc(
        (
            spiral_x - cell * 0.11,
            spiral_y - cell * 0.11,
            spiral_x + cell * 0.11,
            spiral_y + cell * 0.11,
        ),
        start=40,
        end=320,
        fill=255,
        width=2,
    )
    draw.arc(
        (
            spiral_x - cell * 0.05,
            spiral_y - cell * 0.05,
            spiral_x + cell * 0.05,
            spiral_y + cell * 0.05,
        ),
        start=200,
        end=120,
        fill=255,
        width=2,
    )
    draw.ellipse(
        (
            origin_x + cell * 0.18,
            origin_y + cell * 0.78,
            origin_x + cell * 0.18 + 5,
            origin_y + cell * 0.78 + 5,
        ),
        fill=255,
    )


def _tile_coverage(size: tuple[int, int], cell: int = PATTERN_CELL) -> Image.Image:
    """The whole-card vine coverage (half-drop rows so the eye does not lock onto a grid)."""
    key = ("coverage", size, cell)
    cached = _mask_cache.get(key)
    if cached is not None:
        return cached

    tile = _vine_cell(cell)
    coverage = Image.new("L", size, 0)
    shift = cell // 2
    for row, y in enumerate(range(0, size[1], cell)):
        offset = shift if row % 2 else 0
        for x in range(-offset, size[0], cell):
            coverage.paste(tile, (x, y))

    _mask_cache[key] = coverage
    return coverage


def _vine_branch(
    length: int,
    *,
    leaves: int = 6,
    leaf_length: float = 34,
    leaf_width: float = 17,
    width: int = 2,
    swing: float = 14.0,
) -> Image.Image:
    """A golden vine offshoot growing upwards, as an ``L`` mask (rotate it to place it)."""
    pad = int(max(leaf_length, leaf_width)) + 6
    size = (int(swing * 2 + pad * 2), int(length + pad * 2))
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    centre_x = size[0] / 2
    bottom = size[1] - pad

    steps = 30
    stem = [
        (centre_x + swing * math.sin(math.pi * step / steps), bottom - length * step / steps)
        for step in range(steps + 1)
    ]
    draw.line(stem, fill=255, width=width, joint="curve")

    for index in range(max(1, leaves)):
        ratio = 0.14 + index * (0.74 / max(1, leaves - 1))
        x = centre_x + swing * math.sin(math.pi * ratio)
        y = bottom - length * ratio
        slope = swing * math.pi * math.cos(math.pi * ratio)
        angle = math.degrees(math.atan(slope / max(1.0, length)))
        side = 1 if index % 2 == 0 else -1
        draw.polygon(_leaf_points(x, y, leaf_length, leaf_width, angle + 58 * side), fill=255)
        if index % 2:
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=255)

    draw.ellipse(  # a small bud at the tip
        (centre_x - 3, bottom - length - 3, centre_x + 3, bottom - length + 3),
        fill=255,
    )
    return mask


def _laurel_sprig(
    length: int,
    *,
    leaves: int = 3,
    leaf_length: float = 26,
    leaf_width: float = 13,
    width: int = 3,
) -> Image.Image:
    """A little laurel/wheat sprig, as an ``L`` mask (the ribbon ornament)."""
    pad = int(leaf_length) + 6
    size = (int(leaf_length * 2.4), int(length + pad * 2))
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    centre_x = size[0] / 2
    bottom = size[1] - pad
    draw.line([(centre_x, bottom), (centre_x, bottom - length)], fill=190, width=width)

    for index in range(max(1, leaves)):
        ratio = 0.22 + index * (0.62 / max(1, leaves - 1)) if leaves > 1 else 0.5
        y = bottom - length * ratio
        for side in (1, -1):
            draw.polygon(
                _leaf_points(
                    centre_x + side * leaf_length * 0.55,
                    y,
                    leaf_length,
                    leaf_width,
                    side * (90 - (32 + index * 22)),
                ),
                fill=255,
            )
    draw.ellipse((centre_x - 5, bottom - 5, centre_x + 5, bottom + 5), fill=255)
    return mask


def _paste_rotated(
    base: Image.Image,
    layer: Image.Image,
    centre: tuple[float, float],
    angle: float,
) -> Image.Image:
    """Rotate an RGBA layer around its own centre and composite it onto ``base``."""
    rotated = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    canvas = Image.new("RGBA", base.size, (0, 0, 0, 0))
    canvas.paste(
        rotated,
        (round(centre[0] - rotated.width / 2), round(centre[1] - rotated.height / 2)),
    )
    return Image.alpha_composite(base, canvas)


# ------------------------------------------------------------------------------- header
def _brand_coin(language: str) -> Image.Image:
    """The round FOODERA emblem: white disc, gold ring, two eight-pointed stars, wordmark."""
    size = COIN_SIZE
    canvas = Image.new("RGBA", (size, size + COIN_SHADOW_DROP), (0, 0, 0, 0))

    shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow).ellipse((12, 26, size - 13, size + COIN_SHADOW_DROP - 4), fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    canvas = _compose(canvas, _tint(shadow, INK, 150))

    disc = (0, 0, size - 1, size - 1)
    coin = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    coin = _compose(coin, _solid(canvas.size, PAPER), _circle_mask(canvas.size, disc))

    pattern = _tint(_tile_coverage(canvas.size), CREAM_DEEP, 190)
    band = ImageChops.multiply(
        _circle_mask(canvas.size, disc, inner=COIN_ANNULUS[0]),
        _circle_mask(canvas.size, disc, inner=COIN_ANNULUS[1]),
    )
    coin = _compose(coin, pattern, band)

    draw = ImageDraw.Draw(coin)
    draw.ellipse(
        (COIN_RING / 2, COIN_RING / 2, size - 1 - COIN_RING / 2, size - 1 - COIN_RING / 2),
        outline=_rgba(GOLD),
        width=COIN_RING,
    )
    inset = COIN_RING * 1.7
    draw.ellipse(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        outline=_rgba(GOLD, 110),
        width=1,
    )

    star_y = size * COIN_STAR_ROW
    offset = COIN_STAR_OFFSET
    _draw_star(  # the blue star, shifted up-left, in outline
        draw, size / 2 - offset, star_y - offset, COIN_STAR_RADIUS + 2, _rgba(AZURE_DEEP), width=4
    )
    _draw_star(  # the gold star, shifted down-right, solid on top of it
        draw, size / 2 + offset, star_y + offset, COIN_STAR_RADIUS, _rgba(GOLD), filled=True
    )

    wordmark = t("badge.wordmark", language)
    draw.text(
        (size / 2, size * 0.675),
        wordmark,
        font=_fit_text(draw, wordmark, max_size=40, min_size=22, max_width=size * 0.78, bold=True),
        fill=_rgba(AZURE_DEEP),
        anchor="mm",
    )
    year = t("badge.year", language)
    draw.text(
        (size / 2, size * 0.83),
        year,
        font=_fit_text(draw, year, max_size=28, min_size=18, max_width=size * 0.78, bold=True),
        fill=_rgba(GOLD_DEEP),
        anchor="mm",
    )

    return _compose(canvas, coin)


def _draw_header(language: str, logo: Image.Image | None) -> Image.Image:
    """Deep-azure header: gradient, diagonal stripes, gold vines, emblem, date, tagline."""
    size = (BADGE_WIDTH, BADGE_HEIGHT)
    header_size = (BADGE_WIDTH, HEADER_BOTTOM)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))

    header = _linear_gradient(header_size, AZURE_DARK, AZURE_DEEP, direction="diagonal")
    header = Image.alpha_composite(
        header, _diagonal_stripes(header_size, PAPER, alpha=10, period=44, width=12)
    )

    # a soft glow right behind the emblem, so the emblem does not look pasted on
    glow = Image.new("L", (BADGE_WIDTH // 4, HEADER_BOTTOM // 4), 0)
    ImageDraw.Draw(glow).ellipse(
        (
            (COIN_LEFT + COIN_SIZE / 2) / 4 - 42,
            (COIN_TOP + COIN_SIZE / 2) / 4 - 42,
            (COIN_LEFT + COIN_SIZE / 2) / 4 + 42,
            (COIN_TOP + COIN_SIZE / 2) / 4 + 42,
        ),
        fill=46,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(9)).resize(header_size, Image.BICUBIC)
    header = _compose(header, _tint(glow, PAPER))

    branch = _vine_branch(206, leaves=6, leaf_length=34, leaf_width=18)
    header = _paste_rotated(header, _tint(branch, GOLD, 170), (146, 146), 68)
    header = _paste_rotated(
        header, _tint(branch.transpose(Image.FLIP_LEFT_RIGHT), GOLD, 170), (754, 146), -68
    )
    layer.paste(header, (0, 0))

    emblem = Image.new("RGBA", size, (0, 0, 0, 0))
    if logo is None:
        emblem.paste(_brand_coin(language), (COIN_LEFT, COIN_TOP))
    else:
        emblem.paste(logo, _logo_position(logo), logo)
    layer = Image.alpha_composite(layer, emblem)

    draw = ImageDraw.Draw(layer)
    draw.text(
        (BADGE_WIDTH / 2, DATE_Y),
        t("badge.event_line", language),
        font=_load_font(DATE_SIZE),
        fill=_rgba(PAPER, 235),
        anchor="mm",
    )
    _draw_spaced(
        draw,
        (BADGE_WIDTH / 2, TAGLINE_Y),
        t("badge.tagline", language).upper(),
        _load_font(TAGLINE_SIZE, bold=True),
        _rgba(CREAM, 185),
        spacing=2.0,
    )
    return layer


# --------------------------------------------------------------------------------- body
def _draw_band(canvas: Image.Image, language: str) -> Image.Image:
    """The azure ribbon with ``MEHMON`` / ``ГОСТЬ`` and a gold vine at both ends."""
    band_size = (CARD_X1 - CARD_X0 + 1, BAND_BOTTOM - BAND_TOP)
    band = _linear_gradient(band_size, AZURE, AZURE_DEEP, direction="diagonal")
    band = Image.alpha_composite(
        band, _diagonal_stripes(band_size, PAPER, alpha=16, period=38, width=10)
    )
    canvas.paste(band, (CARD_X0, BAND_TOP))

    draw = ImageDraw.Draw(canvas)
    draw.line([(CARD_X0, BAND_TOP), (CARD_X1, BAND_TOP)], fill=_rgba(GOLD), width=2)
    draw.line([(CARD_X0, BAND_BOTTOM - 1), (CARD_X1, BAND_BOTTOM - 1)], fill=_rgba(GOLD), width=2)

    sprig = _laurel_sprig(84, leaves=3, leaf_length=26, leaf_width=13)
    canvas = _paste_rotated(canvas, _tint(sprig, GOLD, 205), (96, BAND_TEXT_Y), -12)
    canvas = _paste_rotated(
        canvas,
        _tint(sprig.transpose(Image.FLIP_LEFT_RIGHT), GOLD, 205),
        (804, BAND_TEXT_Y),
        12,
    )

    draw = ImageDraw.Draw(canvas)
    draw.text(
        (BADGE_WIDTH / 2, BAND_TEXT_Y),
        t("badge.visitor_label", language),
        font=_load_font(BAND_TEXT_SIZE, bold=True),
        fill=_rgba(PAPER),
        anchor="mm",
    )
    return canvas


def _draw_name(canvas: Image.Image, name: str) -> None:
    """The guest name: one line, two lines or a clipped line - always inside the card."""
    draw = ImageDraw.Draw(canvas)
    lines, font = _fit_name(draw, name)
    line_height = round(getattr(font, "size", 48) * NAME_LINE_HEIGHT)
    if len(lines) == 1:
        draw.text((BADGE_WIDTH / 2, NAME_Y), lines[0], font=font, fill=_rgba(INK), anchor="mm")
        return
    top = NAME_Y - line_height * (len(lines) - 1) / 2
    for index, line in enumerate(lines):
        draw.text(
            (BADGE_WIDTH / 2, top + index * line_height),
            line,
            font=font,
            fill=_rgba(INK),
            anchor="mm",
        )


def _draw_divider(canvas: Image.Image) -> None:
    """Two fading gold lines with an eight-pointed gold star between them."""
    inner = BADGE_WIDTH / 2 - DIVIDER_GAP
    outer_left, outer_right = CARD_X0 + 36, CARD_X1 - 36

    for start, end, ramp in (
        (outer_left, inner, [(0.0, 10), (0.78, 215), (1.0, 215)]),
        (BADGE_WIDTH - inner, outer_right, [(0.0, 215), (0.22, 215), (1.0, 10)]),
    ):
        line = Image.new("RGBA", (round(abs(end - start)) + 1, 3), (0, 0, 0, 0))
        ImageDraw.Draw(line).rectangle((0, 1, line.width - 1, 1), fill=_rgba(GOLD))
        line.putalpha(ImageChops.multiply(line.getchannel("A"), _alpha_ramp(line.width, 3, ramp)))
        canvas.paste(line, (round(min(start, end)), DIVIDER_Y - 1), line)

    draw = ImageDraw.Draw(canvas)
    _draw_star(draw, BADGE_WIDTH / 2, DIVIDER_Y, DIVIDER_STAR / 2, _rgba(GOLD), filled=True)
    _draw_star(
        draw,
        BADGE_WIDTH / 2,
        DIVIDER_Y,
        DIVIDER_STAR / 5,
        _rgba(CREAM),
        filled=True,
        inner_ratio=0.5,
    )


def _draw_region(canvas: Image.Image, lead: Lead, lang: str) -> None:
    """Sand pill with the gold contour, the blue map pin and the region of the guest."""
    draw = ImageDraw.Draw(canvas)
    text = _region_text(lead, lang)
    font = _fit_text(
        draw,
        text,
        max_size=REGION_TEXT_MAX_SIZE,
        min_size=REGION_TEXT_MIN_SIZE,
        max_width=REGION_TEXT_MAX_WIDTH,
        bold=True,
    )
    text = _ellipsize(draw, text, font, REGION_TEXT_MAX_WIDTH)  # never runs off the card
    padding = 26
    gap = 12
    pill_width = min(
        REGION_PILL_MAX_WIDTH,
        round(padding * 2 + REGION_PIN + gap + _text_width(draw, text, font)),
    )
    left = BADGE_WIDTH / 2 - pill_width / 2
    top = REGION_Y - REGION_PILL_HEIGHT / 2
    draw.rounded_rectangle(
        (left, top, left + pill_width, top + REGION_PILL_HEIGHT),
        radius=REGION_PILL_HEIGHT // 2,
        fill=_rgba(SAND),
        outline=_rgba(GOLD),
        width=2,
    )

    pin_x = left + padding + REGION_PIN / 2
    draw.ellipse((pin_x - 8, REGION_Y - 13, pin_x + 8, REGION_Y + 3), fill=_rgba(AZURE))
    draw.polygon(
        [(pin_x - 6, REGION_Y + 1), (pin_x + 6, REGION_Y + 1), (pin_x, REGION_Y + 13)],
        fill=_rgba(AZURE),
    )
    draw.ellipse((pin_x - 3, REGION_Y - 8, pin_x + 3, REGION_Y - 2), fill=_rgba(PAPER))

    draw.text(
        (pin_x + REGION_PIN / 2 + gap, REGION_Y),
        text,
        font=font,
        fill=_rgba(INK),
        anchor="lm",
    )


def _qr_tile(payload: str) -> Image.Image:
    """A crisp white QR tile: module size is chosen so the code never has to be scaled."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=QR_BORDER)
    qr.add_data(payload)
    qr.make(fit=True)

    modules = int(qr.modules_count) + 2 * QR_BORDER
    available = QR_SIZE - 2 * QR_INSET
    qr.box_size = max(1, available // modules)

    rendered = qr.make_image(fill_color=INK, back_color=PAPER).convert("RGB")
    tile = Image.new("RGB", (QR_SIZE, QR_SIZE), PAPER)
    if rendered.width > QR_SIZE or rendered.height > QR_SIZE:  # pragma: no cover - huge payload
        rendered = rendered.resize((QR_SIZE, QR_SIZE), Image.NEAREST)
    tile.paste(rendered, ((QR_SIZE - rendered.width) // 2, (QR_SIZE - rendered.height) // 2))
    # the quiet zone is left as a real white square: rounded corners would shave the
    # recommended 4-module margin right where a scanner looks for it
    return tile.convert("RGBA")


def _draw_talon(canvas: Image.Image, payload: str) -> None:
    """The tear-off QR talon: white card, gold contour, scanner corners, perforation."""
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (CARD_LEFT, CARD_TOP, CARD_RIGHT, CARD_BOTTOM),
        radius=CARD_INNER_RADIUS,
        fill=_rgba(PAPER),
        outline=_rgba(GOLD),
        width=2,
    )
    draw.rounded_rectangle(
        (CARD_LEFT + 8, CARD_TOP + 8, CARD_RIGHT - 8, CARD_BOTTOM - 8),
        radius=CARD_INNER_RADIUS - 8,
        outline=_rgba(GOLD, 90),
        width=1,
    )
    canvas.paste(_qr_tile(payload), (QR_LEFT, QR_TOP))

    # blue scanner brackets in the top corners of the talon
    for corner_x, step in ((CARD_LEFT + 10, 1), (CARD_RIGHT - 10, -1)):
        draw.line(
            [
                (corner_x, CARD_TOP + 10 + CARD_BRACKET),
                (corner_x, CARD_TOP + 10),
                (corner_x + step * CARD_BRACKET, CARD_TOP + 10),
            ],
            fill=_rgba(AZURE),
            width=5,
            joint="curve",
        )

    # perforation: a notch in both edges, a dotted gold line and the diamond in the middle
    for notch_x in (CARD_LEFT, CARD_RIGHT):
        draw.ellipse(
            (
                notch_x - TICKET_NOTCH,
                TICKET_DIVIDER_Y - TICKET_NOTCH,
                notch_x + TICKET_NOTCH,
                TICKET_DIVIDER_Y + TICKET_NOTCH,
            ),
            fill=_rgba(CREAM),
        )
    for dot_x in range(CARD_LEFT + 26, CARD_RIGHT - 24, 18):
        draw.line(
            [(dot_x, TICKET_DIVIDER_Y), (dot_x + 9, TICKET_DIVIDER_Y)],
            fill=_rgba(GOLD, 210),
            width=2,
        )
    centre = BADGE_WIDTH / 2
    draw.polygon(
        [
            (centre, TICKET_DIVIDER_Y - 11),
            (centre + 11, TICKET_DIVIDER_Y),
            (centre, TICKET_DIVIDER_Y + 11),
            (centre - 11, TICKET_DIVIDER_Y),
        ],
        fill=_rgba(GOLD),
    )
    draw.polygon(
        [
            (centre, TICKET_DIVIDER_Y - 4),
            (centre + 4, TICKET_DIVIDER_Y),
            (centre, TICKET_DIVIDER_Y + 4),
            (centre - 4, TICKET_DIVIDER_Y),
        ],
        fill=_rgba(PAPER),
    )


def _draw_code(canvas: Image.Image, payload: str) -> None:
    """The lead code under the perforation, letter-spaced like a serial number."""
    _draw_spaced(
        ImageDraw.Draw(canvas),
        (BADGE_WIDTH / 2, CODE_Y),
        payload,
        _load_font(CODE_SIZE, bold=True),
        _rgba(INK),
        spacing=CODE_LETTER_SPACING,
    )


def _draw_hint(canvas: Image.Image, language: str) -> None:
    """The footnote: "show this badge at the entrance"."""
    ImageDraw.Draw(canvas).text(
        (BADGE_WIDTH / 2, HINT_Y),
        t("badge.hint", language),
        font=_load_font(HINT_SIZE),
        fill=_rgba(MUTED),
        anchor="mm",
    )


def _card_canvas(language: str, logo: Image.Image | None) -> Image.Image:
    """Cream card with the vine pattern, the watermark, the side vines and the header."""
    size = (BADGE_WIDTH, BADGE_HEIGHT)
    card_mask = _rounded_mask(size, (CARD_X0, CARD_Y0, CARD_X1, CARD_Y1), CARD_RADIUS)
    canvas = _solid(size, PAPER)
    canvas = _compose(canvas, _solid(size, CREAM), card_mask)
    canvas = _compose(canvas, _tint(_tile_coverage(size), CREAM_DEEP, PATTERN_ALPHA), card_mask)

    watermark = _vine_branch(420, leaves=9, leaf_length=48, leaf_width=24, width=3, swing=18)
    canvas = _paste_rotated(
        canvas, _tint(watermark, GOLD_DEEP, WATERMARK_ALPHA), (450, WATERMARK_Y), 90
    )

    branch = _vine_branch(DECOR_VINE_LENGTH, leaves=7, leaf_length=40, leaf_width=20)
    canvas = _paste_rotated(
        canvas,
        _tint(branch, GOLD, DECOR_VINE_ALPHA),
        (DECOR_VINE_X[0], DECOR_VINE_Y),
        DECOR_VINE_ANGLE,
    )
    canvas = _paste_rotated(
        canvas,
        _tint(branch.transpose(Image.FLIP_LEFT_RIGHT), GOLD, DECOR_VINE_ALPHA),
        (DECOR_VINE_X[1], DECOR_VINE_Y),
        -DECOR_VINE_ANGLE,
    )

    canvas = _compose(canvas, _draw_header(language, logo), card_mask)
    ImageDraw.Draw(canvas).rectangle(  # the gold rule between the header and the body
        (CARD_X0, HEADER_BOTTOM, CARD_X1, RULE_BOTTOM - 1),
        fill=_rgba(GOLD),
    )
    return canvas


def _draw_frame(canvas: Image.Image) -> None:
    """The 2 px gold frame around the whole card (drawn last, so nothing covers it)."""
    ImageDraw.Draw(canvas).rounded_rectangle(
        (CARD_X0, CARD_Y0, CARD_X1, CARD_Y1),
        radius=CARD_RADIUS,
        outline=_rgba(GOLD),
        width=CARD_BORDER,
    )


# -------------------------------------------------------------------------------- badge
def generate_badge(
    lead: Lead,
    lang: str = "uz",
    *,
    logo_path: str | Path | None = None,
) -> bytes:
    """Draw the guest badge for ``lead``; returns the PNG file as bytes.

    Pure picture generation - no Telegram, no database, no files on disk - so the design can
    be unit-tested (signature, size, palette, QR payload) in milliseconds.

    ``logo_path`` is the official-logo slot: omit it and the file in ``app/assets/brand/`` is
    used when the organisers dropped one there, pass a path to point at a file elsewhere, pass
    ``""`` to force the drawn FOODERA emblem.  A logo that cannot be read is simply ignored.
    """
    language = normalize_language(lang)
    selected_logo = _logo_file(logo_path)
    logo = _load_logo(selected_logo) if selected_logo is not None else None

    canvas = _card_canvas(language, logo)
    canvas = _draw_band(canvas, language)
    _draw_name(canvas, _guest_name(lead))
    _draw_divider(canvas)
    _draw_region(canvas, lead, language)
    _draw_talon(canvas, badge_qr_text(lead))
    _draw_code(canvas, badge_qr_text(lead))
    _draw_hint(canvas, language)
    _draw_frame(canvas)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------------------- delivery
async def send_badge(
    bot: Any,
    lead: Lead,
    *,
    lang: str = "uz",
    chat_id: int | None = None,
    caption: str | None = None,
) -> bool:
    """Send the badge as a photo; ``True`` when it reached the chat.

    Every failure (rendering *and* delivery) is swallowed and logged here: the caller is a
    registration flow, and a guest must still finish signing up when Telegram or Pillow
    misbehave.
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

    The single decision point shared by the end of the visitor funnel and the ``/beydjik``
    command, so "exhibitors never receive a badge" is enforced in one place.
    """
    if not enabled:
        return False
    if not is_visitor_lead(lead):
        logger.debug("badge skipped: lead %s is not a visitor", _code_of(lead))
        return False
    return await send_badge(bot, lead, lang=lang, chat_id=chat_id)


def _code_of(lead: Any) -> str:
    return str(getattr(lead, "lead_code", None) or getattr(lead, "id", "?"))
