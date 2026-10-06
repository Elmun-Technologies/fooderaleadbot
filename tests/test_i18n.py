"""Translation catalogs: parity, formatting and label lookups."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.database.models import Lead
from app.flow import STEPS
from app.handlers.engine import build_question
from app.i18n import normalize_language, option_label, t
from app.i18n.catalog_ru import CATALOG as RU
from app.i18n.catalog_uz import CATALOG as UZ
from app.options import OPTION_GROUPS
from app.services.notification import build_lead_card, build_visitor_card

PLACEHOLDER = re.compile(r"\{(\w+)\}")

#: a catalog key that leaked into user-facing text (``t()`` returns the key when it is missing)
LEAKED_KEY = re.compile(
    r"(?<![A-Za-z])(?:q|hint|btn|err|info|success|card|status|cls|opt|progress|support|welcome|help)"
    r"(?:\.[a-z0-9_]+)+(?![A-Za-z])"
)


def keys(catalog: dict[str, str]) -> set[str]:
    return set(catalog)


class TestCatalogParity:
    def test_same_keys_in_both_languages(self) -> None:
        assert keys(UZ) == keys(RU), (
            f"missing in ru: {sorted(keys(UZ) - keys(RU))} / missing in uz: {sorted(keys(RU) - keys(UZ))}"
        )

    def test_no_empty_translations(self) -> None:
        for name, catalog in (("uz", UZ), ("ru", RU)):
            empty = [key for key, value in catalog.items() if not str(value).strip()]
            assert not empty, f"{name}: {empty}"

    def test_placeholders_match_between_languages(self) -> None:
        for key in keys(UZ):
            assert set(PLACEHOLDER.findall(UZ[key])) == set(PLACEHOLDER.findall(RU[key])), key

    def test_no_untranslated_leftovers(self) -> None:
        for key, value in RU.items():
            assert not value.startswith("TODO"), key


class TestCatalogCompleteness:
    def test_event_dates_match_the_updated_schedule(self) -> None:
        assert t("event.dates", "uz") == "📅 27–29 oktabr 2026"
        assert t("event.dates", "ru") == "📅 27–29 октября 2026"

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_every_question_has_a_text(self, language: str) -> None:
        for step_key, step in STEPS.items():
            text = t(step.question_key, language)
            assert text != step.question_key, f"{step_key} has no {language} text"
            if step.hint_key:
                assert t(step.hint_key, language) != step.hint_key

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_every_option_has_a_label(self, language: str) -> None:
        for group, options in OPTION_GROUPS.items():
            for option in options:
                label = t(f"opt.{group}.{option.value}", language)
                assert label != f"opt.{group}.{option.value}", (
                    f"{group}.{option.value} / {language}"
                )

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_every_button_label_exists(self, language: str) -> None:
        for key in (
            "btn.start",
            "btn.back",
            "btn.skip",
            "btn.send_contact",
            "btn.update",
            "btn.continue",
        ):
            assert t(key, language) != key

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_completion_messages_exist(self, language: str) -> None:
        for outcome in ("qualified", "warm", "cold", "visitor"):
            text = t(f"success.{outcome}", language)
            assert text != f"success.{outcome}"
            assert len(text) > 20


class TestRuntimeBehaviour:
    def test_unknown_key_falls_back_to_the_key(self) -> None:
        assert t("definitely.not.here", "uz") == "definitely.not.here"

    def test_missing_placeholder_arguments_do_not_crash(self) -> None:
        assert t("progress", "uz")  # no step/total kwargs -> template returned as-is
        assert "{step}" in t("progress", "uz")

    def test_formatting_works(self) -> None:
        assert t("progress", "uz", step=3, total=10) == "Savol 3/10"
        assert t("progress", "ru", step=3, total=10) == "Вопрос 3/10"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("uz", "uz"),
            ("ru", "ru"),
            ("uz-Cyrl-UZ", "uz"),
            ("ru_RU", "ru"),
            ("en", "uz"),
            (None, "uz"),
            ("", "uz"),
        ],
    )
    def test_language_normalisation(self, raw: str | None, expected: str) -> None:
        assert normalize_language(raw) == expected

    def test_option_label_for_missing_value_is_a_dash(self) -> None:
        assert option_label("category", None, "uz") == t("card.value_none", "uz")

    def test_option_label_for_unknown_value_returns_the_raw_value(self) -> None:
        assert option_label("category", "deleted-category", "uz") == "deleted-category"

    def test_uzbek_uses_latin_script(self) -> None:
        # "Русский" is the name of the other language, that one is allowed
        skipped = {"lang.ru"}
        sample = " ".join(value for key, value in UZ.items() if key not in skipped)
        cyrillic = re.findall(r"[а-яА-ЯёЁ]", sample)
        assert not cyrillic, f"Uzbek catalog contains Cyrillic: {sorted(set(cyrillic))[:5]}"


class TestMaintenance:
    def test_catalogs_are_importable_data_only(self) -> None:
        """No logic in catalog modules - only a CATALOG dict (keeps them reviewable)."""
        source = (Path(__file__).resolve().parents[1] / "app/i18n/catalog_uz.py").read_text(
            encoding="utf-8"
        )
        body = source.split("CATALOG", 1)[1]
        assert "def " not in body
        assert "import " not in body


class TestRenderedCopy:
    """What a person actually reads: the layer where placeholders must already be filled."""

    @staticmethod
    def _lead(language: str) -> Lead:
        return Lead(
            lead_code="FD000001",
            telegram_user_id=1,
            language=language,
            intent="stand",
            company_name="ACME FOOD",
            contact_name="Aziz",
            online_presence="both",
            website="acme.uz",
            phone="+998901234567",
            preferred_stand_size="size_18",
            readiness="ready_to_book",
            score=80,
            classification="HOT",
            lead_status="NEW",
        )

    @staticmethod
    def _buttons(render) -> list[str]:
        labels: list[str] = []
        for markup in (render.keyboard, render.reply_keyboard):
            rows = (
                getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None) or []
            )
            labels.extend(button.text or "" for row in rows for button in row)
        return labels

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_questions_have_no_unfilled_placeholders(self, language: str) -> None:
        lead = self._lead(language)
        for step_key in STEPS:
            render = build_question(lead, step_key, language)
            assert "{" not in render.text and "}" not in render.text, f"{step_key}: {render.text}"

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_no_catalog_key_leaks_into_the_questions(self, language: str) -> None:
        lead = self._lead(language)
        for step_key in STEPS:
            render = build_question(lead, step_key, language)
            assert not LEAKED_KEY.search(render.text), f"{step_key}: {render.text}"
            for label in self._buttons(render):
                assert not LEAKED_KEY.search(label), f"{step_key}: {label}"

    @pytest.mark.parametrize("language", ["uz", "ru"])
    def test_the_cards_are_fully_translated(self, language: str) -> None:
        lead = self._lead(language)
        for card in (
            build_lead_card(lead, lang=language),
            build_visitor_card(lead, lang=language),
        ):
            assert "{" not in card and "}" not in card
            assert not LEAKED_KEY.search(card), card
