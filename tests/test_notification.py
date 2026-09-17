"""Lead card rendering (the message managers see in the sales group)."""

from __future__ import annotations

from app.config import Settings
from app.database.models import Classification, Lead, LeadType, utcnow
from app.i18n import t
from app.keyboards.inline import LEAD_PREFIX, lead_actions_kb
from app.services.notification import (
    MAX_MESSAGE_LENGTH,
    build_lead_card,
    build_visitor_card,
    card_status_line,
)


def make_lead(**overrides: object) -> Lead:
    values: dict[str, object] = {
        "id": 123,
        "lead_code": "FD000123",
        "telegram_user_id": 123456789,
        "telegram_username": "azizbek_karimov",
        "telegram_first_name": "Azizbek",
        "telegram_last_name": "Karimov",
        "language": "uz",
        "source": "telegram_ads",
        "campaign": "foodera",
        "creative": "uz_01",
        "start_payload": "tgads_foodera_uz_01",
        "lead_type": LeadType.EXHIBITOR.value,
        "intent": "stand",
        "company_type": "manufacturer",
        "category": "confectionery_and_bakery",
        "company_name": "SAMARQAND FOOD LLC",
        "region": "samarkand",
        "online_presence": "website",
        "website": "samarqandfood.uz",
        "instagram": "@samarqand_food",
        "contact_name": "Azizbek",
        "position": "Savdo direktori",
        "phone": "+998901234567",
        "preferred_stand_size": "size_18",
        "readiness": "review_options",
        "score": 87,
        "classification": Classification.HOT.value,
        "is_high_intent": False,
        "lead_status": "NEW",
        "created_at": utcnow(),
        "completed_at": utcnow(),
    }
    values.update(overrides)
    return Lead(**values)  # type: ignore[arg-type]


class TestLeadCardContent:
    def test_every_specified_field_is_present(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(), lang="uz", settings=settings)
        assert "SAMARQAND FOOD LLC" in card
        assert "+998901234567" in card
        assert "Samarqand" in card
        assert "Ishlab chiqaruvchi" in card
        assert "Qandolat va non-bulka" in card
        assert "18 m²" in card
        assert "87/100" in card
        assert "FD000123" in card
        assert "tgads_foodera_uz_01" in card
        assert "Telegram Ads" in card
        assert "@azizbek_karimov" in card
        assert "123456789" in card
        assert t("cls.HOT", "uz") in card

    def test_title_and_score_lines(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(), lang="uz", settings=settings)
        assert card.startswith(t("card.title_lead", "uz"))
        assert "🔥" in card.splitlines()[0]

    def test_high_intent_badge(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(is_high_intent=True), lang="uz", settings=settings)
        assert t("card.high_intent", "uz") in card

    def test_no_high_intent_badge_by_default(self, settings: Settings) -> None:
        assert t("card.high_intent", "uz") not in build_lead_card(
            make_lead(), lang="uz", settings=settings
        )

    def test_missing_values_render_as_a_dash(self, settings: Settings) -> None:
        card = build_lead_card(
            make_lead(
                phone=None, website=None, instagram=None, company_name=None, telegram_username=None
            ),
            lang="uz",
            settings=settings,
        )
        assert t("card.value_none", "uz") in card
        assert "None" not in card

    def test_russian_card_when_the_lead_is_russian(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(language="ru"), lang="ru", settings=settings)
        assert "Производитель" in card
        assert "Самарканд" in card
        assert "НОВЫЙ ЛИД" in card

    def test_country_instead_of_region_for_foreign_leads(self, settings: Settings) -> None:
        card = build_lead_card(
            make_lead(region="foreign", country="Казахстан"), lang="ru", settings=settings
        )
        assert "Казахстан" in card
        assert "За пределами" not in card  # country replaces the generic region label

    def test_timestamp_uses_the_configured_timezone(self) -> None:
        settings = Settings(_env_file=None, display_timezone="UTC")
        lead = make_lead(completed_at=utcnow())
        card = build_lead_card(lead, lang="uz", settings=settings)
        assert lead.completed_at.strftime("%d.%m.%Y") in card


class TestSafety:
    def test_markup_in_user_input_is_escaped(self, settings: Settings) -> None:
        evil = '<script>alert("x")</script>'
        card = build_lead_card(
            make_lead(company_name=evil, position=evil), lang="uz", settings=settings
        )
        assert "<script>" not in card
        assert "&lt;script&gt;" in card

    def test_html_entities_in_the_phone_do_not_break_the_link(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(phone='+99890"123'), lang="uz", settings=settings)
        assert card.count('"') % 2 == 0  # quotes are escaped, attributes stay balanced
        assert "tel:" in card

    def test_start_payload_is_rendered_escaped(self, settings: Settings) -> None:
        card = build_lead_card(
            make_lead(start_payload="tgads_<b>x</b>"), lang="uz", settings=settings
        )
        assert "<b>x</b>" not in card

    def test_long_answers_are_capped(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(company_name="A" * 400), lang="uz", settings=settings)
        assert len(card) <= MAX_MESSAGE_LENGTH


class TestStatusLine:
    def test_new_status_is_shown_before_any_manager_action(self, settings: Settings) -> None:
        card = build_lead_card(make_lead(), lang="uz", settings=settings)
        assert t("card.status_line", "uz", status=t("status.NEW", "uz")) in card

    def test_manager_and_time_are_appended_after_a_change(self, settings: Settings) -> None:
        lead = make_lead(
            lead_status="BOOKED", manager_username="manager_bot", status_changed_at=utcnow()
        )
        line = card_status_line(lead, "uz")
        assert t("status.BOOKED", "uz") in line
        assert "@manager_bot" in line

    def test_card_shows_the_current_status(self, settings: Settings) -> None:
        lead = make_lead(lead_status="NEGOTIATION")
        assert t("status.NEGOTIATION", "uz") in build_lead_card(lead, lang="uz", settings=settings)


class TestVisitorCard:
    def test_visitor_card_has_no_commercial_fields(self, settings: Settings) -> None:
        lead = make_lead(
            lead_type=LeadType.VISITOR.value,
            classification=Classification.VISITOR.value,
            business_relation="student",
            preferred_stand_size=None,
            score=0,
        )
        card = build_visitor_card(lead, lang="uz", settings=settings)
        assert t("card.title_visitor", "uz") in card
        assert "Talaba" in card
        assert "m²" not in card
        assert "/100" not in card

    def test_visitor_card_still_has_contact_details(self, settings: Settings) -> None:
        lead = make_lead(lead_type=LeadType.VISITOR.value, business_relation="retail")
        card = build_visitor_card(lead, lang="uz", settings=settings)
        assert "+998901234567" in card
        assert "FD000123" in card


class TestActionKeyboard:
    def test_four_manager_buttons(self) -> None:
        keyboard = lead_actions_kb(7, "uz")
        flat = [button for row in keyboard.inline_keyboard for button in row]
        assert len(flat) == 4
        assert all(
            button.callback_data and button.callback_data.startswith(f"{LEAD_PREFIX}:7:")
            for button in flat
        )

    def test_callback_ids_are_short_enough_for_telegram(self) -> None:
        keyboard = lead_actions_kb(999_999, "ru")
        for row in keyboard.inline_keyboard:
            for button in row:
                assert button.callback_data is not None and len(button.callback_data) <= 64
                assert button.text is not None and len(button.text) <= 64
