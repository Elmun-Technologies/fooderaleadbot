"""Guest badge (``MEHMON BEYDJIGI``): the drawing itself, the delivery and the funnel.

Two layers are covered here:

* :func:`generate_badge` - a pure function, so the picture is asserted directly: PNG
  signature, 900x1200 canvas, the texts that are painted on it (uz *and* ru), a 40+ char
  name and, above all, a QR code that really contains the ``lead_code``;
* the funnel wiring - a guest who finishes the questionnaire receives the badge as a
  photo, an exhibitor never does, and a badge that cannot be drawn or delivered leaves
  the registration finished and intact.
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
from app.options import Intent
from app.services import badge_service
from app.services.badge_service import (
    QR_BORDER,
    QR_LEFT,
    QR_SIZE,
    QR_TOP,
    badge_caption,
    badge_filename,
    badge_qr_text,
    generate_badge,
    is_visitor_lead,
    maybe_send_badge,
    send_badge,
)
from PIL import Image
from qrcode.constants import ERROR_CORRECT_M

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: long enough to force the two-line / smaller-font path (and then the ellipsis path)
LONG_NAME = (
    "Jasurbek Abdullayevich Rakhmonberdiyev Norboyev Qodirov Ismoilov Karimberdiyev Abdusattorov"
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


# --------------------------------------------------------------------- the drawing
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

    def test_paints_the_event_the_label_the_name_the_region_and_the_code(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(), "uz")

        painted = "\n".join(entry[0] for entry in drawn)
        assert "FOODERA EXPO 2026" in painted
        assert "27–29 oktabr 2026 · SOF EXPO, Samarqand" in painted
        assert "MEHMON" in painted
        assert "Malika Rahimova" in painted
        assert "Samarqand" in painted
        assert "FD000123" in painted
        assert "Kirishda ushbu beydjikni ko‘rsating" in painted

    def test_russian_badge_uses_the_russian_catalog(self) -> None:
        with painted_text() as drawn:
            generate_badge(badge_lead(language="ru"), "ru")

        painted = "\n".join(entry[0] for entry in drawn)
        assert "ГОСТЬ" in painted
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
        assert sizes and max(sizes) < 78, "a name this long cannot use the largest font"

    def test_a_very_long_name_is_wrapped_and_clipped_but_never_leaves_the_card(self) -> None:
        with painted_text() as drawn:
            data = generate_badge(badge_lead(contact_name=LONG_NAME))

        assert data.startswith(PNG_SIGNATURE)
        lines = name_lines(drawn)
        assert len(lines) == 2, f"a {len(LONG_NAME)} character name must wrap onto two lines"
        assert LONG_NAME.startswith(lines[0]), "the first line starts at the beginning of the name"
        assert lines[-1].endswith("…"), "what does not fit is clipped with an ellipsis"

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

    def test_missing_fonts_degrade_to_the_builtin_font(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """python:3.11-slim without fonts-dejavu-core must not break the funnel."""
        monkeypatch.setattr(badge_service, "BOLD_FONT_PATHS", ("/nope/missing-bold.ttf",))
        monkeypatch.setattr(badge_service, "REGULAR_FONT_PATHS", ("/nope/missing.ttf",))
        badge_service._font_cache.clear()
        try:
            assert generate_badge(badge_lead()).startswith(PNG_SIGNATURE)
        finally:
            badge_service._font_cache.clear()

    def test_fonts_are_cached_between_badges(self) -> None:
        badge_service._font_cache.clear()
        generate_badge(badge_lead())
        cached = dict(badge_service._font_cache)
        generate_badge(badge_lead(lead_code="FD000999"))
        assert cached and set(cached) <= set(badge_service._font_cache)


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
