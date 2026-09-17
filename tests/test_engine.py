"""Pure parts of the question engine: rendering, answer mapping, error cases."""

from __future__ import annotations

import pytest
from app.database.models import Lead, LeadType
from app.flow import StepError, StepKind
from app.handlers.engine import apply_inline_answer, apply_phone, apply_text_answer, build_question
from app.options import Intent, OnlinePresence, Region


def lead(**values: object) -> Lead:
    base: dict[str, object] = {
        "id": 1,
        "lead_code": "FD000001",
        "telegram_user_id": 1,
        "language": "uz",
        "lead_type": LeadType.EXHIBITOR.value,
        "intent": Intent.STAND,
    }
    base.update(values)
    return Lead(**base)  # type: ignore[arg-type]


class TestRendering:
    def test_progress_counter_and_question(self) -> None:
        render = build_question(lead(), "company_type", "uz")
        assert render.text.startswith("Savol 2/")
        assert "Kompaniyangiz qaysi turga kiradi?" in render.text
        assert render.keyboard is not None

    def test_inline_keyboard_offers_every_option(self) -> None:
        render = build_question(lead(), "company_type", "uz")
        assert render.keyboard is not None
        flat = [button for row in render.keyboard.inline_keyboard for button in row]
        labels = " ".join(button.text or "" for button in flat)
        assert "Ishlab chiqaruvchi" in labels
        assert "🏭" in labels
        callbacks = [button.callback_data for button in flat]
        assert "q:company_type:manufacturer" in callbacks
        assert "nav:back" in callbacks

    def test_first_question_has_no_back_button(self) -> None:
        render = build_question(lead(intent=None), "intent", "uz")
        callbacks = [b.callback_data for row in render.keyboard.inline_keyboard for b in row]
        assert "nav:back" not in callbacks

    def test_phone_step_uses_a_reply_keyboard(self) -> None:
        render = build_question(lead(), "phone", "uz")
        assert render.reply_keyboard is not None
        first_row = render.reply_keyboard.keyboard[0]
        assert first_row[0].request_contact is True

    def test_optional_steps_offer_skip(self) -> None:
        render = build_question(lead(), "url", "uz")
        callbacks = [b.callback_data for row in render.keyboard.inline_keyboard for b in row]
        assert "nav:skip" in callbacks

    def test_category_keyboard_is_paginated(self) -> None:
        render = build_question(lead(), "category", "uz")
        flat = [b for row in render.keyboard.inline_keyboard for b in row]
        assert len(flat) <= 10  # 8 options + pagination / back, never 16 buttons at once
        assert any((b.callback_data or "").startswith("cat:page:") for b in flat)

    def test_selected_option_is_marked(self) -> None:
        render = build_question(lead(company_type="manufacturer"), "company_type", "uz")
        flat = [b.text or "" for row in render.keyboard.inline_keyboard for b in row]
        assert any(text.startswith("✓") for text in flat)

    def test_error_is_appended_to_the_question(self) -> None:
        render = build_question(lead(), "company_name", "ru", error="Слишком коротко")
        assert "⚠️" in render.text
        assert "Слишком коротко" in render.text

    def test_russian_localization(self) -> None:
        render = build_question(lead(), "intent", "ru")
        assert "Вопрос 1/" in render.text
        assert "Что вас интересует" in render.text
        labels = " ".join(b.text or "" for row in render.keyboard.inline_keyboard for b in row)
        assert "гость" in labels

    def test_hint_and_previous_answer_are_shown(self) -> None:
        render = build_question(lead(company_name="Old Name"), "company_name", "uz")
        assert "2 tadan 120 tagacha belgi." in render.text
        assert "Old Name" in render.text


class TestInlineAnswerMapping:
    def test_intent(self) -> None:
        from app.flow import STEPS

        assert apply_inline_answer(STEPS["intent"], Intent.STAND, lead()) == {
            "intent": Intent.STAND
        }

    def test_region_clears_a_stale_country(self) -> None:
        from app.flow import STEPS

        local = apply_inline_answer(STEPS["region"], Region.SAMARKAND, lead(country="Kazakhstan"))
        assert local == {"region": Region.SAMARKAND, "country": None}
        foreign = apply_inline_answer(STEPS["region"], Region.FOREIGN, lead(country="Kazakhstan"))
        assert foreign == {"region": Region.FOREIGN, "country": "Kazakhstan"}

    def test_declining_online_presence_clears_links(self) -> None:
        from app.flow import STEPS

        values = apply_inline_answer(
            STEPS["online"], OnlinePresence.NONE, lead(website="a.uz", instagram="@a")
        )
        assert values == {"online_presence": "none", "website": None, "instagram": None}

    def test_forged_callback_value_is_rejected(self) -> None:
        from app.flow import STEPS

        with pytest.raises(StepError):
            apply_inline_answer(STEPS["stand"], "size_9999", lead())

    def test_option_outside_the_current_step_is_rejected(self) -> None:
        from app.flow import STEPS

        with pytest.raises(StepError):
            apply_inline_answer(STEPS["intent"], "manufacturer", lead())


class TestTextAnswerMapping:
    def test_company_name_is_trimmed(self) -> None:
        from app.flow import STEPS

        assert apply_text_answer(STEPS["company_name"], "  ACME FOOD  ") == {
            "company_name": "ACME FOOD"
        }

    def test_contact_line_is_split(self) -> None:
        from app.flow import STEPS

        values = apply_text_answer(STEPS["contact"], "Azizbek — Savdo direktori")
        assert values == {"contact_name": "Azizbek", "position": "Savdo direktori"}

    def test_contact_line_without_position_keeps_the_raw_value(self) -> None:
        from app.flow import STEPS

        values = apply_text_answer(STEPS["contact"], "Azizbek Karimov")
        assert values["contact_name"] == "Azizbek Karimov"
        assert values["position"] is None

    def test_url_answer_is_split_into_two_fields(self) -> None:
        from app.flow import STEPS

        values = apply_text_answer(STEPS["url"], "food.uz\n@food")
        assert values == {"website": "food.uz", "instagram": "@food"}

    def test_garbage_url_is_rejected(self) -> None:
        from app.flow import STEPS

        with pytest.raises(StepError) as exc:
            apply_text_answer(STEPS["url"], "yo'q")
        assert exc.value.message_key == "err.url_format"

    def test_short_company_name_is_rejected_with_a_localized_key(self) -> None:
        from app.flow import STEPS

        with pytest.raises(StepError) as exc:
            apply_text_answer(STEPS["company_name"], "A")
        assert exc.value.message_key == "err.company_name_len"

    def test_visitor_name_writes_contact_name(self) -> None:
        from app.flow import STEPS

        assert apply_text_answer(STEPS["visitor_name"], "Malika") == {"contact_name": "Malika"}


class TestPhoneAnswer:
    def test_valid_number(self) -> None:
        assert apply_phone("+998 90 123 45 67") == {"phone": "+998901234567"}

    def test_invalid_number_raises_the_phone_error(self) -> None:
        with pytest.raises(StepError) as exc:
            apply_phone("hello")
        assert exc.value.message_key == "err.phone_format"


class TestStepKinds:
    @pytest.mark.parametrize(
        ("step_key", "kind"),
        [
            ("intent", StepKind.INLINE),
            ("category", StepKind.CATEGORY),
            ("company_name", StepKind.TEXT),
            ("url", StepKind.URL),
            ("phone", StepKind.PHONE),
            ("visitor_name", StepKind.TEXT),
            ("visitor_phone", StepKind.PHONE),
        ],
    )
    def test_kinds(self, step_key: str, kind: StepKind) -> None:
        from app.flow import STEPS

        assert STEPS[step_key].kind is kind
