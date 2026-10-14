"""Guest badge (``MEHMON BEYDJIGI``): the FOODERA brand design, the delivery and the funnel.

Three layers are covered here:

* :func:`generate_badge` - a pure function, so the picture is asserted directly: PNG signature,
  900x1200 canvas, the brand palette actually on the pixels (cream card, 2 px gold frame,
  azure header and ribbon, white QR talon), the emblem with its blue *and* gold star, the
  official-logo slot (including a broken file), the texts that are painted (uz *and* ru), a
  40+ character name and, above all, a QR code that still encodes the ``lead_code`` byte for
  byte and can be read back out of the PNG;
* the font chain - DejaVu -> a system font that really prints ``ГОСТЬ`` -> PIL's built-in font,
  never a crash;
* the funnel wiring - a guest who finishes the questionnaire receives the badge as a photo, an
  exhibitor never does, and a badge that cannot be drawn or delivered leaves the registration
  finished and intact (plus ``/beydjik``, the panel download and the Telegram menu).
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import qrcode
from aiogram.types import BufferedInputFile
from app.config import Settings
from app.database.models import BotUser, Lead, LeadType
from app.database.repository import LeadRepository
from app.flow import STEPS
from app.handlers.engine import Context, finish
from app.i18n import t
from app.i18n.catalog_ru import CATALOG as RU
from app.i18n.catalog_uz import CATALOG as UZ
from app.options import Intent
from app.services import badge_service
from app.services.badge_service import (
    CARD_X0,
    CARD_Y0,
    CODE_LETTER_SPACING,
    CODE_SIZE,
    CODE_Y,
    COIN_LEFT,
    COIN_SIZE,
    COIN_TOP,
    DATE_Y,
    DIVIDER_STAR,
    DIVIDER_Y,
    HEADER_BOTTOM,
    HINT_Y,
    NAME_Y,
    QR_BORDER,
    QR_LEFT,
    QR_SIZE,
    QR_TOP,
    REGION_Y,
    TICKET_DIVIDER_Y,
    badge_caption,
    badge_filename,
    badge_qr_text,
    clear_font_cache,
    generate_badge,
    is_visitor_lead,
    maybe_send_badge,
    resolve_font_path,
    resolve_logo_path,
    send_badge,
)
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_M

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: long enough to force the two-line / smaller-font path (and then the ellipsis path)
LONG_NAME = (
    "Jasurbek Abdullayevich Rakhmonberdiyev Norboyev Qodirov Ismoilov Karimberdiyev Abdusattorov"
)

#: strings that are painted onto the PNG with DejaVu - which has no emoji glyphs
BADGE_PAINTED_KEYS = (
    "badge.wordmark",
    "badge.year",
    "badge.tagline",
    "badge.event_line",
    "badge.visitor_label",
    "badge.hint",
)

EMOJI_RANGES = (
    (0x200D, 0x200D),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0xFE0F, 0xFE0F),
    (0x1F000, 0x1FAFF),
)


def badge_lead(**values: Any) -> Lead:
    base: dict[str, Any] = {
        "id": 1,
        "lead_code": "FD000123",
        "telegram_user_id": 4242,
        "telegram_first_name": "Malika",
        "language": "uz",
        "lead_type": LeadType.VISITOR.value,
        "intent": Intent.VISITOR.value,
        "contact_name": "Malika Rahimova",
        "region": "samarkand",
    }
    base.update(values)
    return Lead(**base)


def render(lead: Lead | None = None, lang: str = "uz", **kwargs: Any) -> Image.Image:
    """The badge as a Pillow image - what the guest (and the printer) sees."""
    data = generate_badge(lead or badge_lead(), lang, **kwargs)
    return Image.open(io.BytesIO(data)).convert("RGB")


def near(pixel: tuple[int, int, int], colour: str, tolerance: int = 20) -> bool:
    expected = badge_service._rgb(colour)
    return all(
        abs(value - target) <= tolerance for value, target in zip(pixel, expected, strict=True)
    )


def is_bluish(pixel: tuple[int, int, int], minimum: int = 60) -> bool:
    red, green, blue = pixel
    return blue > red + minimum and blue > green + 20


MAX_COLOURS = 1 << 24


def get_counts(image: Image.Image) -> list[tuple[int, tuple[int, int, int]]]:
    """``[(pixel count, colour), ...]`` of an image - ``getcolors`` without the Pillow warning."""
    return image.getcolors(maxcolors=MAX_COLOURS) or []  # type: ignore[return-value]


def count_colour(
    image: Image.Image,
    colour: str,
    *,
    box: tuple[int, int, int, int] | None = None,
    tolerance: int = 20,
) -> int:
    """How many pixels of the badge match ``colour`` (optionally inside ``box``)."""
    if box is not None:
        image = image.crop(box)
    return sum(count for count, pixel in get_counts(image) if near(pixel, colour, tolerance))


# --------------------------------------------------------------------------- fakes
@contextmanager
def painted_text() -> Iterator[list[tuple[str, int | None, tuple[float, float]]]]:
    """Collect every string Pillow actually draws - and with which font size.

    Reading the PNG back only proves that *something* was painted; the texts and the font
    sizes are the part of the design worth asserting on.
    """
    drawn: list[tuple[str, int | None, tuple[float, float]]] = []
    original = badge_service.ImageDraw.ImageDraw.text
    cached_fonts = dict(badge_service._font_cache)

    def spy(self, xy, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        font = kwargs.get("font")
        drawn.append((str(text), getattr(font, "size", None), xy))
        return original(self, xy, text, *args, **kwargs)

    badge_service.ImageDraw.ImageDraw.text = spy  # type: ignore[method-assign]
    try:
        yield drawn
    finally:
        badge_service.ImageDraw.ImageDraw.text = original  # type: ignore[method-assign]
        # fonts loaded before are reused, never dropped - the picture must be identical
        for key, font in cached_fonts.items():
            assert badge_service._font_cache.get(key) is font, key


def letter_spaced(drawn: list[tuple[str, int | None, tuple[float, float]]]) -> str:
    """The letter-spaced runs (the tagline, the lead code) stitched back into one string."""
    return "".join(entry[0] for entry in drawn if len(entry[0]) == 1)


#: the name is centred on NAME_Y; two lines at the largest font reach ~50 px away from it
NAME_BAND = 60


def name_lines(drawn: list[tuple[str, int | None, tuple[float, float]]]) -> list[str]:
    """Texts painted in the name band of the card, top to bottom."""
    band = [
        (entry[2][1], entry[0])
        for entry in drawn
        if abs(entry[2][1] - badge_service.NAME_Y) <= NAME_BAND
    ]
    return [line for _y, line in sorted(band)]


class FakeBot:
    """Records ``send_photo`` calls instead of talking to Telegram."""

    def __init__(self, *, fail: bool = False) -> None:
        self.photos: list[dict[str, Any]] = []
        self._fail = fail

    async def send_photo(self, **kwargs: Any) -> None:
        self.photos.append(kwargs)
        if self._fail:
            raise RuntimeError("telegram is unhappy")

    @property
    def captions(self) -> list[str]:
        return [str(photo.get("caption") or "") for photo in self.photos]

    @property
    def images(self) -> list[bytes]:
        return [
            bytes(photo["photo"].data)  # BufferedInputFile keeps the PNG in memory
            for photo in self.photos
            if isinstance(photo.get("photo"), BufferedInputFile)
        ]


class FakeMessage:
    """A private-chat message good enough for :func:`app.handlers.engine.finish`."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.texts: list[str] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.texts.append(text)

    @property
    def last_text(self) -> str:
        return self.texts[-1] if self.texts else ""


class FakeState:
    def __init__(self) -> None:
        self.cleared = 0

    async def clear(self) -> None:
        self.cleared += 1


def read_qr_modules(image: Image.Image) -> tuple[list[list[bool]], int]:
    """Decode the QR symbol painted on the badge into a module grid.

    Independent of the rendering internals: the symbol is located as the dark bounding box
    inside its white tile, the module size is derived from the QR version, and every module
    is then sampled at its centre.
    """
    tile = image.crop((QR_LEFT, QR_TOP, QR_LEFT + QR_SIZE, QR_TOP + QR_SIZE)).convert("L")
    pixels = tile.load()
    width, height = tile.size

    dark = [(x, y) for y in range(height) for x in range(width) if pixels[x, y] < 128]
    assert dark, "the badge has no QR code at all"

    x0 = min(x for x, _ in dark)
    y0 = min(y for _, y in dark)
    x1 = max(x for x, _ in dark)
    y1 = max(y for _, y in dark)
    span = x1 - x0 + 1
    assert span == y1 - y0 + 1, "the QR symbol is not square"

    # The version is unknown, but the module size must divide the symbol evenly and the
    # three finder patterns have to show up - that is what makes a grid a QR code.
    candidates: list[tuple[int, list[list[bool]]]] = []
    for version in range(1, 41):
        modules = 17 + 4 * version
        if span % modules or span // modules < 2:
            continue
        box = span // modules
        grid = [
            [
                pixels[x0 + column * box + box // 2, y0 + row * box + box // 2] < 128
                for column in range(modules)
            ]
            for row in range(modules)
        ]
        if all(
            _has_finder_pattern(grid, top=top, left=left)
            for top, left in ((0, 0), (0, modules - 7), (modules - 7, 0))
        ):
            candidates.append((box, grid))

    assert candidates, "no QR module grid could be read from the badge"
    box, grid = max(candidates, key=lambda candidate: candidate[0])
    return grid, box


def _has_finder_pattern(grid: list[list[bool]], *, top: int, left: int) -> bool:
    """The 7x7 corner marker of a QR code: a full border, a light ring, a 3x3 core."""
    for row in range(7):
        for column in range(7):
            expected = row in (0, 6) or column in (0, 6) or (2 <= row <= 4 and 2 <= column <= 4)
            if grid[top + row][left + column] is not expected:
                return False
    return True


def qr_matrix(payload: str) -> list[list[bool]]:
    """The reference matrix ``qrcode`` produces for ``payload`` (same parameters)."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=0)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


# ------------------------------------------------------------------------- the palette
class TestBrandPalette:
    """The FOODERA colours: exact values, and every one of them is a valid hex string."""

    def test_the_palette_mapping_matches_the_constants(self) -> None:
        assert badge_service.PALETTE == {
            "PAPER": badge_service.PAPER,
            "CREAM": badge_service.CREAM,
            "CREAM_DEEP": badge_service.CREAM_DEEP,
            "INK": badge_service.INK,
            "AZURE_DARK": badge_service.AZURE_DARK,
            "AZURE": badge_service.AZURE,
            "AZURE_DEEP": badge_service.AZURE_DEEP,
            "GOLD": badge_service.GOLD,
            "GOLD_DEEP": badge_service.GOLD_DEEP,
            "SAND": badge_service.SAND,
            "MUTED": badge_service.MUTED,
            "FAINT": badge_service.FAINT,
        }

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("PAPER", "#FFFFFF"),
            ("CREAM", "#FAF6EE"),
            ("CREAM_DEEP", "#EEE7D9"),
            ("INK", "#0C283C"),
            ("AZURE_DARK", "#0C3E60"),
            ("AZURE", "#2A8FC7"),
            ("AZURE_DEEP", "#126091"),
            ("GOLD", "#C9A96A"),
            ("GOLD_DEEP", "#A6884F"),
            ("SAND", "#F2EBDE"),
            ("MUTED", "#5A6976"),
            ("FAINT", "#96A0AA"),
        ],
    )
    def test_the_official_colour_values(self, name: str, expected: str) -> None:
        assert badge_service.PALETTE[name] == expected

    def test_every_colour_is_convertible_to_rgb(self) -> None:
        for name, value in badge_service.PALETTE.items():
            red, green, blue = badge_service._rgb(value)
            assert (0, 0, 0) <= (red, green, blue) <= (255, 255, 255), name


# ---------------------------------------------------------------------- the drawing
class TestGenerateBadge:
    def test_returns_a_png(self) -> None:
        data = generate_badge(badge_lead())
        assert isinstance(data, bytes)
        assert data.startswith(PNG_SIGNATURE), "a PDF/JPEG would not be accepted as a badge"

    def test_canvas_is_900_by_1200(self) -> None:
        image = Image.open(io.BytesIO(generate_badge(badge_lead())))
        assert image.size == (900, 1200)
        assert image.format == "PNG"

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_works_in_both_languages(self, language: str) -> None:
        assert generate_badge(badge_lead(language=language), language).startswith(PNG_SIGNATURE)

    def test_unknown_language_falls_back_to_uzbek(self) -> None:
        assert generate_badge(badge_lead(), "en") == generate_badge(badge_lead(), "uz")

    def test_the_same_lead_always_renders_the_same_png(self) -> None:
        """The design is deterministic - no random noise, no timestamps, no font drift."""
        assert generate_badge(badge_lead()) == generate_badge(badge_lead())

    def test_paints_the_wordmark_the_ribbon_the_name_the_region_and_the_code(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(), "uz")

        painted = "\n".join(entry[0] for entry in drawn)
        spaced = letter_spaced(drawn)
        assert "FOODERA" in painted
        assert "EXPO 2026" in painted
        assert t("badge.tagline", "uz").upper() in spaced, "the tagline is letter-spaced"
        assert "27–29 oktabr 2026 · SOF EXPO, Samarqand" in painted
        assert "MEHMON" in painted
        assert "Malika Rahimova" in painted
        assert "Samarqand" in painted
        assert "FD000123" in spaced, "the lead code is letter-spaced too"
        assert "Kirishda ushbu beydjikni ko‘rsating" in painted

    def test_russian_badge_uses_the_russian_catalog(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(language="ru"), "ru")

        painted = "\n".join(entry[0] for entry in drawn)
        spaced = letter_spaced(drawn)
        assert "ГОСТЬ" in painted
        assert t("badge.tagline", "ru").upper() in spaced
        assert "Покажите этот бейдж на входе" in painted
        assert "27–29 октября 2026 · SOF EXPO, Самарканд" in painted

    def test_a_40_plus_character_name_does_not_crash_and_shrinks_to_fit(self) -> None:
        name = "Abdullayevich Rakhmonberdiyev Norboyev Qodirov"  # 46 characters
        assert len(name) >= 40
        with painted_text() as drawn:
            data = generate_badge(badge_lead(contact_name=name))

        assert data.startswith(PNG_SIGNATURE)
        lines = name_lines(drawn)
        assert lines, "the name must still be printed"
        assert len(lines) <= 2, "the badge reserves two lines for the name"
        assert " ".join(lines) == name, "a 46 character name must not be cut"
        sizes = [size for text_, size, _xy in drawn if text_ in lines]
        assert sizes and max(sizes) <= badge_service.NAME_TWO_LINE_SIZE, (
            "it cannot use the 74 px line"
        )

    def test_a_two_line_name_fits_the_name_width(self) -> None:
        name = "Abdullayevich Rakhmonberdiyev Norboyev Qodirov"
        with painted_text() as drawn:
            image = render(badge_lead(contact_name=name))
        lines = name_lines(drawn)
        sizes = {size for text_, size, _xy in drawn if text_ in lines}
        assert len(lines) == 2 and len(sizes) == 1, (lines, sizes)
        size = sizes.pop()
        assert 0 < size <= badge_service.NAME_TWO_LINE_SIZE
        probe = ImageDraw.Draw(image)
        font = badge_service._load_font(size, bold=True)
        assert all(
            probe.textlength(line, font=font) <= badge_service.NAME_MAX_WIDTH for line in lines
        ), "both lines have to stay inside the card"

    def test_a_short_name_stays_on_one_line_at_the_largest_size(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(contact_name="Malika Rahimova"))
        lines = name_lines(drawn)
        assert lines == ["Malika Rahimova"]
        assert [size for text_, size, _xy in drawn if text_ == "Malika Rahimova"] == [
            badge_service.NAME_MAX_SIZE
        ]

    def test_a_very_long_name_is_wrapped_and_clipped_but_never_leaves_the_card(self) -> None:
        with painted_text() as drawn:
            data = generate_badge(badge_lead(contact_name=LONG_NAME))

        assert data.startswith(PNG_SIGNATURE)
        lines = name_lines(drawn)
        assert len(lines) == 2, f"a {len(LONG_NAME)} character name must wrap onto two lines"
        assert LONG_NAME.startswith(lines[0]), "the first line starts at the beginning of the name"
        assert lines[-1].endswith("…"), "what does not fit is clipped with an ellipsis"

    def test_a_two_line_name_is_centred_on_its_anchor(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(contact_name=LONG_NAME))
        y_values = sorted(
            {y for text_, _size, (x, y) in drawn if abs(y - NAME_Y) <= NAME_BAND and x == 450}
        )
        assert len(y_values) == 2, y_values
        middle = (y_values[0] + y_values[1]) / 2
        assert abs(middle - NAME_Y) <= 1, "the two lines have to sit around NAME_Y"

    def test_a_single_giant_word_is_ellipsized_instead_of_overflowing(self) -> None:
        word = "A" * 120
        with painted_text() as drawn:
            data = generate_badge(badge_lead(contact_name=word))

        assert data.startswith(PNG_SIGNATURE)
        lines = name_lines(drawn)
        assert lines and all(line.endswith("…") for line in lines), lines

    def test_name_falls_back_to_the_telegram_profile(self) -> None:
        lead = badge_lead(contact_name=None, telegram_username="malika")
        assert generate_badge(lead).startswith(PNG_SIGNATURE)

    def test_a_missing_region_does_not_crash(self) -> None:
        assert generate_badge(badge_lead(region=None)).startswith(PNG_SIGNATURE)

    def test_a_foreign_guest_shows_the_country(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(region="foreign", country="Qozog‘iston"), "uz")

        assert "Qozog‘iston" in "\n".join(entry[0] for entry in drawn)

    def test_a_very_long_region_shrinks_and_stays_inside_its_pill(self) -> None:
        country = "Qozog‘iston Respublikasining shimoli-sharqiy hududi"
        with painted_text() as drawn:
            image = render(badge_lead(region="foreign", country=country))

        painted = [
            (text_, size, xy)
            for text_, size, xy in drawn
            if size is not None
            and size <= badge_service.REGION_TEXT_MAX_SIZE
            and text_.startswith("Qozog‘iston")
        ]
        assert len(painted) == 1, painted
        text_, size, (start_x, centre_y) = painted[0]
        assert size == badge_service.REGION_TEXT_MIN_SIZE, "the pill shrinks to its floor"
        assert text_.endswith("…") and country.startswith(text_[:-1].rstrip()), text_
        assert abs(centre_y - REGION_Y) <= 1
        width = ImageDraw.Draw(image).textlength(
            text_, font=badge_service._load_font(size, bold=True)
        )
        half = badge_service.REGION_PILL_MAX_WIDTH / 2
        assert 450 - half <= start_x and start_x + width <= 450 + half, "the text left the pill"

    def test_fonts_are_cached_between_badges(self) -> None:
        badge_service._font_cache.clear()
        generate_badge(badge_lead())
        cached = dict(badge_service._font_cache)
        generate_badge(badge_lead(lead_code="FD000999"))
        assert cached and set(cached) <= set(badge_service._font_cache)


class TestBrandLook:
    """The colours that end up on the pixels - the part the client actually judges."""

    def test_the_card_is_cream_on_white_paper(self) -> None:
        image = render()
        outside = image.getpixel((4, 4))  # the paper margin around the card
        inside = image.getpixel((40, 600))
        assert near(outside, badge_service.PAPER, 6), outside
        assert near(inside, badge_service.CREAM, 8), inside

    def test_the_card_is_framed_by_a_two_pixel_gold_border(self) -> None:
        image = render()
        assert near(image.getpixel((CARD_X0, 600)), badge_service.GOLD, 12)
        assert near(image.getpixel((CARD_X0 + 1, 600)), badge_service.GOLD, 12)
        assert near(image.getpixel((450, CARD_Y0)), badge_service.GOLD, 12)

    def test_the_header_is_deep_azure(self) -> None:
        pixel = render().getpixel((200, 120))
        assert is_bluish(pixel, 60), pixel
        assert sum(pixel) < 330, f"the header must stay dark blue, got {pixel}"

    def test_the_gold_rule_sits_under_the_header(self) -> None:
        image = render()
        assert near(image.getpixel((450, HEADER_BOTTOM + 4)), badge_service.GOLD, 12)
        assert near(image.getpixel((450, HEADER_BOTTOM + 10)), badge_service.GOLD, 12)

    def test_the_ribbon_is_azure(self) -> None:
        pixel = render().getpixel((200, badge_service.BAND_TEXT_Y))
        assert is_bluish(pixel, 60), pixel

    def test_the_ribbon_has_gold_edges(self) -> None:
        image = render()
        assert near(image.getpixel((450, badge_service.BAND_TOP)), badge_service.GOLD, 40)
        assert near(image.getpixel((450, badge_service.BAND_BOTTOM - 1)), badge_service.GOLD, 40)

    def test_the_qr_talon_is_white_on_the_cream_card(self) -> None:
        image = render()
        talon = image.getpixel((280, 1000))
        card = image.getpixel((100, 1000))
        assert talon == (255, 255, 255), talon
        assert badge_service._rgb(badge_service.CREAM)[0] - 6 < card[0] < 256, card
        assert sum(talon) > sum(card), "the talon has to stand out from the card"

    def test_the_talon_has_blue_scanner_brackets(self) -> None:
        image = render()
        left_arm = image.getpixel((badge_service.CARD_LEFT + 10, badge_service.CARD_TOP + 30))
        right_arm = image.getpixel((badge_service.CARD_RIGHT - 10, badge_service.CARD_TOP + 30))
        top_arm = image.getpixel((badge_service.CARD_LEFT + 30, badge_service.CARD_TOP + 10))
        for pixel in (left_arm, right_arm, top_arm):
            assert is_bluish(pixel, 40), pixel

    def test_the_talon_has_a_perforation_with_a_gold_diamond(self) -> None:
        image = render()
        assert near(image.getpixel((450, TICKET_DIVIDER_Y - 7)), badge_service.GOLD, 25), (
            "no diamond"
        )
        assert image.getpixel((450, TICKET_DIVIDER_Y)) == (255, 255, 255)
        dots = [
            1
            for x in range(badge_service.CARD_LEFT + 20, badge_service.CARD_RIGHT - 20)
            if near(image.getpixel((x, TICKET_DIVIDER_Y)), badge_service.GOLD, 40)
        ]
        assert len(dots) > 10, "the dotted tear line is missing"

    def test_the_region_pill_is_sand_with_a_blue_pin(self) -> None:
        image = render()
        band = image.crop((180, REGION_Y - 20, 720, REGION_Y + 20))
        assert count_colour(band, badge_service.SAND, tolerance=6) > 500, "no sand pill"
        assert any(is_bluish(pixel, 60) for _count, pixel in get_counts(band)), (
            "the map pin is missing"
        )

    def test_the_side_vines_are_drawn_beside_the_talon(self) -> None:
        """Two golden branches at alpha 60 - warm ink that the white talon cannot show."""
        image = render()

        def warm(box: tuple[int, int, int, int]) -> int:
            """Pixels tinted by the golden vine: warm ink the cream paper cannot produce."""
            return sum(
                count
                for count, (red, _green, blue) in get_counts(image.crop(box))
                if red - blue > 34
            )

        left = warm((60, 820, 240, 1020))
        right = warm((660, 820, 840, 1020))
        blank = warm((280, 950, 460, 1040))  # inside the white QR talon
        assert left > 200 and right > 200, (left, right)
        assert abs(left - right) <= max(20, left * 0.08), (left, right)
        assert left > blank, (left, blank)

    def test_the_hint_is_painted_at_the_bottom(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead())
        hinted = [xy for text_, _size, xy in drawn if text_ == t("badge.hint", "uz")]
        assert hinted and abs(hinted[0][1] - HINT_Y) <= 1

    def test_the_lead_code_is_letter_spaced(self) -> None:
        """Every character is placed individually, ``CODE_LETTER_SPACING`` apart."""
        payload = "FD000123"
        with painted_text() as drawn:
            generate_badge(badge_lead(lead_code=payload))

        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        font = badge_service._load_font(CODE_SIZE, bold=True)
        widths = [probe.textlength(char, font=font) for char in payload]
        x = 450 - (sum(widths) + CODE_LETTER_SPACING * (len(payload) - 1)) / 2
        expected = []
        for width in widths:
            expected.append(round(x + width / 2))
            x += width + CODE_LETTER_SPACING

        painted = [
            xy
            for text_, size, xy in drawn
            if size == CODE_SIZE and text_ in payload and abs(xy[1] - CODE_Y) <= 1
        ]
        assert len(painted) == len(payload), painted
        assert [round(px) for px, _py in painted] == expected

    def test_the_divider_star_sits_between_two_gold_lines(self) -> None:
        image = render()
        assert near(image.getpixel((450, DIVIDER_Y - DIVIDER_STAR // 3)), badge_service.GOLD, 25), (
            "no gold star"
        )
        assert near(image.getpixel((450, DIVIDER_Y)), badge_service.CREAM, 5), "the star is hollow"
        for x in (350, 550):
            assert near(image.getpixel((x, DIVIDER_Y)), badge_service.GOLD, 30), (x, "line missing")

    def test_the_divider_lines_fade_out_towards_the_frame(self) -> None:
        image = render()
        faded = image.getpixel((CARD_X0 + 40, DIVIDER_Y))
        bright = image.getpixel((300, DIVIDER_Y))
        assert sum(faded) > sum(bright), "the line has to fade out (ramp)"

    def test_the_whole_card_carries_the_vine_pattern(self) -> None:
        """The cream paper is patterned: the body has many distinct shades, not one flat fill."""
        body = render().crop((40, 380, 300, 700))
        assert len(get_counts(body)) > 12, "the vine pattern is missing"


class TestBrandCoin:
    """The round emblem: white disc, gold ring, a blue *and* a gold star, the wordmark."""

    def test_the_emblem_paints_the_wordmark_and_the_year(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(), "uz")
        sizes = {text_: size for text_, size, _xy in drawn}
        assert "FOODERA" in sizes and sizes["FOODERA"] is not None
        assert 24 <= sizes["FOODERA"] <= 40, sizes["FOODERA"]
        assert "EXPO 2026" in sizes and 18 <= sizes["EXPO 2026"] < sizes["FOODERA"]

    def test_the_emblem_paints_the_wordmark_in_russian_too(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(language="ru"), "ru")
        painted = [entry[0] for entry in drawn]
        assert "FOODERA" in painted and "EXPO 2026" in painted, "the emblem is language independent"

    def test_the_emblem_holds_both_a_blue_and_a_gold_star(self) -> None:
        image = render()
        box = (COIN_LEFT, COIN_TOP, COIN_LEFT + COIN_SIZE, COIN_TOP + COIN_SIZE)
        assert count_colour(image, badge_service.AZURE_DEEP, box=box, tolerance=45) > 400
        assert count_colour(image, badge_service.GOLD, box=box, tolerance=45) > 400

    def test_the_emblem_is_a_disc_inside_the_header(self) -> None:
        image = render()
        white = image.getpixel((COIN_LEFT + 30, COIN_TOP + 116))
        assert sum(white) > 600, f"the disc has to be light, got {white}"
        assert is_bluish(image.getpixel((COIN_LEFT - 30, COIN_TOP + 20)), 60), "no header around it"

    def test_the_emblem_sits_above_the_date_line(self) -> None:
        assert COIN_TOP + COIN_SIZE < DATE_Y
        assert badge_service.HEADER_BOTTOM < badge_service.BAND_TOP

    def test_the_two_stars_overlap(self) -> None:
        """Two eight-pointed outlines, shifted apart - not one star drawn twice."""
        offset = badge_service.COIN_STAR_OFFSET
        assert 0 < offset < badge_service.COIN_STAR_RADIUS
        points = badge_service._star_points(0, 0, badge_service.COIN_STAR_RADIUS)
        assert len(points) == 16, "an eight-pointed star has sixteen vertices"
        angles = [round((i * 180 / 8) % 360) for i in range(8)]
        assert angles == sorted(angles), "the vertices have to alternate evenly"


class TestLogoSlot:
    """``logo_path``: the official FOODERA logo, when the organisers drop one in."""

    @staticmethod
    def _logo(tmp_path: Any, *, size: tuple[int, int] = (400, 200), colour: str = "#00C000") -> Any:
        path = tmp_path / "official.png"
        Image.new("RGBA", size, (*badge_service._rgb(colour), 255)).save(path)
        return path

    def test_a_logo_file_replaces_the_drawn_emblem(self, tmp_path: Any) -> None:
        path = self._logo(tmp_path)
        with painted_text() as drawn, pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "BRAND_DIR", tmp_path / "nowhere")
            image = render(**{"logo_path": path})

        assert near(image.getpixel((450, COIN_TOP + COIN_SIZE // 2)), "#00C000", 20), "no logo"
        assert "FOODERA" not in "\n".join(entry[0] for entry in drawn), "the emblem must be gone"

    def test_a_logo_is_scaled_into_the_560x260_slot(self, tmp_path: Any) -> None:
        path = self._logo(tmp_path, size=(1200, 600))
        image = render(**{"logo_path": path})
        green = [
            (x, y)
            for y in range(0, 320)
            for x in range(0, 900)
            if near(image.getpixel((x, y)), "#00C000", 25)
        ]
        assert green, "the logo is not on the badge"
        width = max(x for x, _ in green) - min(x for x, _ in green) + 1
        height = max(y for _, y in green) - min(y for _, y in green) + 1
        assert width <= badge_service.LOGO_MAX_WIDTH
        assert height <= badge_service.LOGO_MAX_HEIGHT
        assert (width, height) == (520, 260), (width, height)

    def test_the_logo_keeps_its_aspect_ratio(self, tmp_path: Any) -> None:
        path = self._logo(tmp_path, size=(1500, 500))
        image = render(**{"logo_path": path})
        green = [
            (x, y)
            for y in range(0, 320)
            for x in range(0, 900)
            if near(image.getpixel((x, y)), "#00C000", 25)
        ]
        width = max(x for x, _ in green) - min(x for x, _ in green) + 1
        height = max(y for _, y in green) - min(y for _, y in green) + 1
        assert abs(width / height - 3.0) < 0.1, (width, height)

    def test_the_logo_is_centred_on_the_card(self, tmp_path: Any) -> None:
        path = self._logo(tmp_path, size=(400, 200))
        image = render(**{"logo_path": path})
        green = [
            (x, y)
            for y in range(0, 320)
            for x in range(0, 900)
            if near(image.getpixel((x, y)), "#00C000", 25)
        ]
        left = min(x for x, _ in green)
        right = max(x for x, _ in green)
        assert abs((left + right) / 2 - 450) <= 1
        middle = (min(y for _, y in green) + max(y for _, y in green)) / 2
        assert abs(middle - (COIN_TOP + COIN_SIZE / 2)) <= 2

    def test_a_broken_logo_file_is_ignored(self, tmp_path: Any, caplog: Any) -> None:
        path = tmp_path / "renamed.pdf"
        path.write_bytes(b"%PDF-1.7 not an image at all")
        with painted_text() as drawn:
            data = generate_badge(badge_lead(), "uz", logo_path=path)

        assert data.startswith(PNG_SIGNATURE), "a broken logo must never break the badge"
        assert "FOODERA" in "\n".join(entry[0] for entry in drawn), "the emblem has to be back"
        assert "could not be read" in caplog.text

    def test_a_missing_logo_path_is_ignored(self, tmp_path: Any) -> None:
        assert generate_badge(badge_lead(), logo_path=tmp_path / "nope.png").startswith(
            PNG_SIGNATURE
        )

    def test_an_empty_logo_path_forces_the_drawn_emblem(self, tmp_path: Any) -> None:
        Image.new("RGBA", (100, 100), (0, 192, 0, 255)).save(tmp_path / "logo.png")
        with pytest.MonkeyPatch.context() as patch, painted_text() as drawn:
            patch.setattr(badge_service, "BRAND_DIR", tmp_path)
            data = generate_badge(badge_lead(), "uz", logo_path="")
        assert data.startswith(PNG_SIGNATURE)
        assert "FOODERA" in "\n".join(entry[0] for entry in drawn)

    def test_the_brand_folder_is_used_when_no_path_is_given(self, tmp_path: Any) -> None:
        Image.new("RGBA", (100, 100), (0, 192, 0, 255)).save(tmp_path / "logo.png")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "BRAND_DIR", tmp_path)
            assert resolve_logo_path() == tmp_path / "logo.png"
            image = render()
        assert near(image.getpixel((450, COIN_TOP + COIN_SIZE // 2)), "#00C000", 20)

    def test_without_a_file_the_brand_folder_resolves_to_nothing(self, tmp_path: Any) -> None:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "BRAND_DIR", tmp_path)
            assert resolve_logo_path() is None

    def test_the_brand_readme_documents_the_slot_and_the_palette(self) -> None:
        readme = badge_service.BRAND_DIR / "README.md"
        assert readme.is_file(), "app/assets/brand/README.md documents how to drop a logo in"
        text = readme.read_text(encoding="utf-8")
        assert "logo.png" in text
        for name, colour in badge_service.PALETTE.items():
            assert colour in text, f"{name} ({colour}) is missing from the brand README"


# ---------------------------------------------------------------------- the font chain
class TestFontChain:
    """DejaVu -> a system font that really prints ``ГОСТЬ`` -> PIL's built-in bitmap font."""

    def setup_method(self) -> None:
        clear_font_cache()

    def teardown_method(self) -> None:
        clear_font_cache()

    def test_dejavu_wins_when_it_is_installed(self) -> None:
        first = badge_service.REGULAR_FONT_PATHS[0]
        if not badge_service._usable(first):
            pytest.skip("fonts-dejavu-core is not installed on this host")
        assert resolve_font_path() == first
        assert resolve_font_path(bold=True) == badge_service.BOLD_FONT_PATHS[0]

    def test_the_chain_falls_back_to_a_system_font_with_cyrillic(self) -> None:
        fallback = next(
            (path for path in badge_service.REGULAR_FONT_PATHS if badge_service._usable(path)),
            None,
        )
        if fallback is None:  # pragma: no cover - no font at all on the host
            pytest.skip("no system font to fall back to")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf", fallback))
            assert resolve_font_path() == fallback

    def test_a_font_without_cyrillic_is_rejected(self) -> None:
        hidden = next(
            (path for path in badge_service.REGULAR_FONT_PATHS if badge_service._usable(path)), None
        )
        if hidden is None:  # pragma: no cover
            pytest.skip("no system font on this host")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", (hidden,))
            patch.setattr(badge_service, "_renders_cyrillic", lambda *a, **k: False)
            assert resolve_font_path() is None, "ГОСТЬ must never be painted as tofu boxes"

    def test_missing_fonts_are_reported_once(self, caplog: Any) -> None:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf",))
            assert resolve_font_path() is None
        assert "Cyrillic" in caplog.text

    def test_dejavu_really_paints_the_russian_ribbon_label(self) -> None:
        path = next(
            (item for item in badge_service.BOLD_FONT_PATHS if badge_service._usable(item)), None
        )
        if path is None:  # pragma: no cover
            pytest.skip("no system font on this host")
        assert badge_service._renders_cyrillic(path), "the bold face must print ГОСТЬ"
        assert not badge_service._renders_cyrillic("/nope/missing.ttf")

    def test_a_file_that_is_not_a_font_is_not_usable(self, tmp_path: Any) -> None:
        fake = tmp_path / "broken.ttf"
        fake.write_bytes(b"definitely not a TrueType font")
        assert badge_service._usable(fake) is False
        assert badge_service._usable(tmp_path / "missing.ttf") is False

    def test_the_resolved_path_is_cached_until_the_cache_is_cleared(self) -> None:
        first = resolve_font_path()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf",))
            assert resolve_font_path() == first, "a repeated call must not re-walk the chain"
        clear_font_cache()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf",))
            assert resolve_font_path() is None

    def test_missing_fonts_degrade_to_the_builtin_font(self) -> None:
        """python:3.11-slim without fonts-dejavu-core must not break the funnel."""
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "BOLD_FONT_PATHS", ("/nope/missing-bold.ttf",))
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf",))
            clear_font_cache()
            try:
                assert generate_badge(badge_lead()).startswith(PNG_SIGNATURE)
            finally:
                clear_font_cache()

    def test_the_fallback_never_crashes_on_cyrillic(self) -> None:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(badge_service, "BOLD_FONT_PATHS", ("/nope/missing-bold.ttf",))
            patch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf",))
            clear_font_cache()
            try:
                assert generate_badge(badge_lead(language="ru"), "ru").startswith(PNG_SIGNATURE)
            finally:
                clear_font_cache()


# ------------------------------------------------------------------------ the QR code
class TestQrCode:
    def test_the_qr_encodes_the_lead_code(self) -> None:
        payloads: list[str] = []
        original = qrcode.QRCode.add_data

        def spy(self, data, *args, **kwargs):  # type: ignore[no-untyped-def]
            payloads.append(str(data))
            return original(self, data, *args, **kwargs)

        qrcode.QRCode.add_data = spy
        try:
            generate_badge(badge_lead(lead_code="FD000123"))
        finally:
            qrcode.QRCode.add_data = original

        assert payloads == ["FD000123"]

    def test_the_painted_matrix_is_exactly_the_qr_of_the_lead_code(self) -> None:
        """Decode the badge: every module must match a freshly built QR for the code."""
        image = Image.open(io.BytesIO(generate_badge(badge_lead(lead_code="FD000123"))))
        grid, _version = read_qr_modules(image)
        assert grid == qr_matrix("FD000123")

    def test_a_different_lead_code_produces_a_different_qr(self) -> None:
        first, _ = read_qr_modules(
            Image.open(io.BytesIO(generate_badge(badge_lead(lead_code="FD000123"))))
        )
        second, _ = read_qr_modules(
            Image.open(io.BytesIO(generate_badge(badge_lead(lead_code="FD000777"))))
        )
        assert first != second
        assert second == qr_matrix("FD000777")

    def test_the_qr_keeps_a_quiet_zone(self) -> None:
        """A QR without a light border cannot be scanned off a printed badge."""
        image = Image.open(io.BytesIO(generate_badge(badge_lead()))).convert("L")
        tile = image.crop((QR_LEFT, QR_TOP, QR_LEFT + QR_SIZE, QR_TOP + QR_SIZE))
        margin = QR_BORDER + 1  # inside the tile, outside the symbol
        corners = [
            tile.getpixel((margin, margin)),
            tile.getpixel((QR_SIZE - margin, margin)),
            tile.getpixel((margin, QR_SIZE - margin)),
            tile.getpixel((QR_SIZE - margin, QR_SIZE - margin)),
        ]
        assert all(pixel > 200 for pixel in corners), corners

    def test_the_qr_tile_is_square_and_centred_on_the_card(self) -> None:
        assert QR_LEFT * 2 + QR_SIZE == badge_service.BADGE_WIDTH
        assert badge_service.CARD_LEFT < QR_LEFT < QR_LEFT + QR_SIZE < badge_service.CARD_RIGHT

    def test_badge_qr_text_falls_back_to_the_user_id(self) -> None:
        assert badge_qr_text(badge_lead(lead_code="")) == "4242"

    def test_filename_is_derived_from_the_lead_code(self) -> None:
        assert badge_filename(badge_lead()) == "FD000123_badge.png"

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_caption_is_the_expected_thank_you(self, language: str) -> None:
        caption = badge_caption(language)
        assert caption.startswith("🎫")
        assert "/start" not in caption


# ------------------------------------------------------------------------ who gets one
class TestVisitorDetection:
    def test_visitor_leads_qualify(self) -> None:
        assert is_visitor_lead(badge_lead())
        assert is_visitor_lead(badge_lead(lead_type=None, intent=Intent.VISITOR.value))

    @pytest.mark.parametrize(
        "values",
        [
            {"lead_type": LeadType.EXHIBITOR.value, "intent": Intent.STAND.value},
            {"lead_type": LeadType.PARTNER.value, "intent": Intent.PARTNER.value},
            {"lead_type": "exhibitor", "intent": Intent.STAND.value},
        ],
    )
    def test_everybody_else_does_not(self, values: dict[str, Any]) -> None:
        assert not is_visitor_lead(badge_lead(**values))


# --------------------------------------------------------------------------- delivery
class TestSendBadge:
    async def test_sends_a_buffered_photo_with_the_caption(self) -> None:
        bot = FakeBot()
        assert await send_badge(bot, badge_lead(), lang="uz") is True
        assert len(bot.photos) == 1
        photo = bot.photos[0]
        assert isinstance(photo["photo"], BufferedInputFile)
        assert photo["photo"].filename == "FD000123_badge.png"
        assert bytes(photo["photo"].data).startswith(PNG_SIGNATURE)
        assert photo["chat_id"] == 4242  # straight to the guest, never to the sales group
        assert "🎫" in photo["caption"]

    async def test_a_render_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*args: Any, **kwargs: Any) -> bytes:
            raise OSError("no fonts here")

        monkeypatch.setattr(badge_service, "generate_badge", boom)
        bot = FakeBot()
        assert await send_badge(bot, badge_lead()) is False
        assert bot.photos == []

    async def test_a_telegram_failure_is_swallowed(self) -> None:
        bot = FakeBot(fail=True)
        assert await send_badge(bot, badge_lead()) is False

    async def test_no_bot_is_not_an_error(self) -> None:
        assert await send_badge(None, badge_lead()) is False

    async def test_explicit_chat_id_wins(self) -> None:
        bot = FakeBot()
        await send_badge(bot, badge_lead(), chat_id=99)
        assert bot.photos[0]["chat_id"] == 99


class TestMaybeSendBadge:
    async def test_sends_for_a_guest_when_enabled(self) -> None:
        bot = FakeBot()
        assert await maybe_send_badge(bot, badge_lead(), enabled=True) is True
        assert len(bot.photos) == 1

    async def test_skips_when_the_feature_is_off(self) -> None:
        bot = FakeBot()
        assert await maybe_send_badge(bot, badge_lead(), enabled=False) is False
        assert bot.photos == []

    @pytest.mark.parametrize(
        "values",
        [
            {"lead_type": LeadType.EXHIBITOR.value, "intent": Intent.STAND.value},
            {"lead_type": LeadType.PARTNER.value, "intent": Intent.PARTNER.value},
        ],
    )
    async def test_exhibitors_and_partners_never_get_a_badge(self, values: dict[str, Any]) -> None:
        bot = FakeBot()
        assert await maybe_send_badge(bot, badge_lead(**values), enabled=True) is False
        assert bot.photos == [], "the exhibitor segment must never receive a badge"


# ------------------------------------------------------------------ the visitor funnel
async def run_visitor_finish(
    repo: LeadRepository,
    settings: Settings,
    user: BotUser,
    *,
    bot: Any,
    values: dict[str, Any],
) -> Any:
    """Finish a stored visitor application exactly like the engine does."""
    lead = await repo.create_lead(
        telegram_user_id=user.telegram_user_id,
        language="uz",
        **values,
    )
    from app.services.lead_service import LeadService

    message = FakeMessage(bot)
    ctx = Context(
        lead=lead,
        step=STEPS["visitor_region"],
        state=FakeState(),
        leads=LeadService(repo, settings, None),
        repo=repo,
        settings=settings,
        lang="uz",
        event=message,  # type: ignore[arg-type]
    )
    result = await finish(ctx)
    return result, message


class TestVisitorFunnelBadge:
    async def test_a_guest_receives_the_badge_after_the_thank_you_message(
        self, repo: LeadRepository, settings: Settings, user: BotUser
    ) -> None:
        bot = FakeBot()
        result, message = await run_visitor_finish(
            repo,
            settings,
            user,
            bot=bot,
            values={
                "lead_type": LeadType.VISITOR.value,
                "intent": Intent.VISITOR.value,
                "contact_name": "Malika",
                "region": "samarkand",
            },
        )

        assert result.outcome == "visitor"
        assert "Rahmat" in message.last_text  # the registration message went out first
        assert len(bot.photos) == 1, "the badge must be sent automatically"
        assert bot.images[0].startswith(PNG_SIGNATURE)
        assert "🎫" in bot.captions[0]
        assert "SOF EXPO" in bot.captions[0]
        assert bot.photos[0]["chat_id"] == user.telegram_user_id

    async def test_the_lead_is_completed_even_when_the_badge_cannot_be_drawn(
        self,
        repo: LeadRepository,
        settings: Settings,
        user: BotUser,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(*args: Any, **kwargs: Any) -> bytes:
            raise RuntimeError("Pillow is having a day off")

        monkeypatch.setattr(badge_service, "generate_badge", boom)
        bot = FakeBot()

        result, message = await run_visitor_finish(
            repo,
            settings,
            user,
            bot=bot,
            values={
                "lead_type": LeadType.VISITOR.value,
                "intent": Intent.VISITOR.value,
                "contact_name": "Malika",
                "region": "tashkent",
            },
        )

        assert result.outcome == "visitor"  # the flow finished, nothing was rolled back
        assert "Rahmat" in message.last_text
        assert bot.photos == []

        stored = await repo.get_lead(result.lead.id)
        assert stored is not None and stored.completed_at is not None

    async def test_the_lead_is_completed_even_when_telegram_rejects_the_photo(
        self, repo: LeadRepository, settings: Settings, user: BotUser
    ) -> None:
        bot = FakeBot(fail=True)
        result, message = await run_visitor_finish(
            repo,
            settings,
            user,
            bot=bot,
            values={
                "lead_type": LeadType.VISITOR.value,
                "intent": Intent.VISITOR.value,
                "contact_name": "Malika",
                "region": "bukhara",
            },
        )
        assert result.outcome == "visitor"
        assert "Rahmat" in message.last_text

    async def test_an_exhibitor_never_gets_a_badge_from_the_funnel(
        self, repo: LeadRepository, settings: Settings, user: BotUser
    ) -> None:
        bot = FakeBot()
        result, _message = await run_visitor_finish(
            repo,
            settings,
            user,
            bot=bot,
            values={
                "lead_type": LeadType.EXHIBITOR.value,
                "intent": Intent.STAND.value,
                "company_name": "SAMARQAND FOOD LLC",
                "contact_name": "Azizbek",
                "region": "samarkand",
            },
        )
        assert result.outcome != "visitor"
        assert bot.photos == []

    async def test_the_badge_can_be_turned_off_from_the_env(
        self, repo: LeadRepository, settings: Settings, user: BotUser
    ) -> None:
        settings.visitor_badge_enabled = False
        bot = FakeBot()
        result, message = await run_visitor_finish(
            repo,
            settings,
            user,
            bot=bot,
            values={
                "lead_type": LeadType.VISITOR.value,
                "intent": Intent.VISITOR.value,
                "contact_name": "Malika",
                "region": "namangan",
            },
        )
        assert result.outcome == "visitor"
        assert "Rahmat" in message.last_text
        assert bot.photos == []


# ------------------------------------------------------------------ the admin panel
class TestPanelDownload:
    """``GET /admin/leads/{id}/badge`` - the print desk at the venue."""

    async def _visitor(self, repo: LeadRepository, user: BotUser) -> Lead:
        return await repo.create_lead(
            telegram_user_id=user.telegram_user_id,
            language="uz",
            lead_type=LeadType.VISITOR.value,
            intent=Intent.VISITOR.value,
            contact_name="Malika",
            region="samarkand",
        )

    async def test_a_visitor_lead_downloads_as_a_png_file(
        self, repo: LeadRepository, user: BotUser, settings: Settings
    ) -> None:
        from app.web.routers.leads import download_badge

        lead = await self._visitor(repo, user)
        response = await download_badge(lead_id=lead.id, user="admin", lang="uz", repo=repo)

        assert response.status_code == 200
        assert response.media_type == "image/png"
        assert response.headers["content-disposition"] == (
            f'attachment; filename="{lead.lead_code}_badge.png"'
        )
        assert bytes(response.body).startswith(PNG_SIGNATURE)

    async def test_the_downloaded_badge_is_the_brand_design(
        self, repo: LeadRepository, user: BotUser
    ) -> None:
        from app.web.routers.leads import download_badge

        lead = await self._visitor(repo, user)
        response = await download_badge(lead_id=lead.id, user="admin", lang="uz", repo=repo)
        image = Image.open(io.BytesIO(bytes(response.body))).convert("RGB")
        assert near(image.getpixel((CARD_X0, 600)), badge_service.GOLD, 12), "no gold frame"
        assert near(image.getpixel((40, 600)), badge_service.CREAM, 8), "no cream card"

    async def test_an_exhibitor_lead_has_no_badge(
        self, repo: LeadRepository, user: BotUser
    ) -> None:
        from app.web.routers.leads import download_badge

        lead = await repo.create_lead(
            telegram_user_id=user.telegram_user_id,
            language="uz",
            lead_type=LeadType.EXHIBITOR.value,
            intent=Intent.STAND.value,
            company_name="SAMARQAND FOOD LLC",
        )
        response = await download_badge(lead_id=lead.id, user="admin", lang="uz", repo=repo)
        assert response.status_code == 404

    async def test_an_unknown_lead_is_a_404(self, repo: LeadRepository) -> None:
        from app.web.routers.leads import download_badge

        response = await download_badge(lead_id=999_999, user="admin", lang="uz", repo=repo)
        assert response.status_code == 404

    async def test_a_render_failure_does_not_500_the_panel(
        self, repo: LeadRepository, user: BotUser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.web.routers import leads as leads_router

        def boom(*args: Any, **kwargs: Any) -> bytes:
            raise RuntimeError("no fonts")

        monkeypatch.setattr(leads_router, "generate_badge", boom)
        lead = await self._visitor(repo, user)
        response = await leads_router.download_badge(
            lead_id=lead.id, user="admin", lang="uz", repo=repo
        )
        assert response.status_code == 500
        assert b"PNG" not in bytes(response.body)

    def test_the_template_offers_the_button_for_visitors_only(self) -> None:
        from app.web.routers import leads as leads_router

        template = (leads_router.TEMPLATES_DIR / "lead_detail.html").read_text(encoding="utf-8")
        assert "/badge" in template
        assert "lead.lead_type == 'visitor' or lead.intent == 'visitor'" in template


# ------------------------------------------------------------------- the Telegram menu
class TestCommandMenu:
    """``/beydjik`` is advertised exactly while the feature is enabled."""

    def test_the_command_is_offered_when_the_feature_is_on(self, settings: Settings) -> None:
        from app.bot import command_list

        for language, expected in (("uz", "🎫 Beydjikni olish"), ("ru", "🎫 Получить бейдж")):
            commands = {
                command.command: command.description for command in command_list(language, settings)
            }
            assert commands.get("beydjik") == expected, language

    def test_the_command_disappears_when_the_feature_is_off(self, settings: Settings) -> None:
        from app.bot import command_list

        settings.visitor_badge_enabled = False
        names = [command.command for command in command_list("uz", settings)]
        assert "beydjik" not in names

    def test_telegram_only_accepts_lowercase_latin_command_names(self) -> None:
        from app.bot import command_list

        for command in command_list("uz", settings=Settings(_env_file=None)):
            assert command.command == command.command.lower()
            assert command.command.isascii()
            assert len(command.description) <= 256


# ------------------------------------------------------------------------- the catalog
class TestBadgeCatalog:
    """The brand moved the event title into ``wordmark`` + ``year`` + ``tagline``."""

    def test_the_new_keys_exist_in_both_catalogs(self) -> None:
        for key in ("badge.wordmark", "badge.year", "badge.tagline"):
            assert key in UZ, key
            assert key in RU, key

    def test_the_old_event_title_key_is_gone(self) -> None:
        assert "badge.event_title" not in UZ
        assert "badge.event_title" not in RU

    def test_the_taglines_are_the_expected_ones(self) -> None:
        assert UZ["badge.tagline"] == "OZIQ-OVQAT VA ICHIMLIKLAR KO‘RGAZMASI"
        assert RU["badge.tagline"] == "ВЫСТАВКА ПРОДУКТОВ ПИТАНИЯ И НАПИТКОВ"

    def test_the_wordmark_and_the_year_are_language_independent(self) -> None:
        assert UZ["badge.wordmark"] == RU["badge.wordmark"] == "FOODERA"
        assert UZ["badge.year"] == RU["badge.year"] == "EXPO 2026"

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_no_painted_text_carries_an_emoji(self, language: str) -> None:
        """DejaVu has no emoji glyphs - a 🎫 on the PNG would be a tofu box in print."""
        with painted_text() as drawn:
            generate_badge(badge_lead(language=language), language)

        def has_emoji(text: str) -> bool:
            return any(low <= ord(char) <= high for char in text for low, high in EMOJI_RANGES)

        offending = [entry[0] for entry in drawn if has_emoji(entry[0])]
        assert not offending, offending

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_every_painted_key_is_drawn_on_the_png(self, language: str) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(language=language), language)

        painted = "\n".join(entry[0] for entry in drawn)
        spaced = letter_spaced(drawn)
        for key in BADGE_PAINTED_KEYS:
            value = t(key, language)
            haystack = spaced if key == "badge.tagline" else painted
            expected = value.upper() if key == "badge.tagline" else value
            assert expected in haystack, f"{key} is not painted on the badge"
