"""Phone normalisation (Uzbekistan + international)."""

from __future__ import annotations

import pytest
from app.utils.phone import extract_phone_from_text, normalize_phone


class TestUzbekistanNumbers:
    @pytest.mark.parametrize(
        "raw",
        [
            "+998901234567",
            "998901234567",
            "+998 90 123 45 67",
            "+998 (90) 123-45-67",
            "8 90 123 45 67",
            "901234567",
            "90 123 45 67",
            "00 998 90 123 45 67",
        ],
    )
    def test_all_land_on_the_same_e164(self, raw: str) -> None:
        result = normalize_phone(raw)
        assert result.valid is True
        assert result.number == "+998901234567"


class TestInternationalNumbers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("+7 916 123 45 67", "+79161234567"),
            ("+49 151 2345 678", "+491512345678"),
            ("+998 90 123 45 67", "+998901234567"),
            ("+1 (202) 555-0143", "+12025550143"),
            ("+998901234567", "+998901234567"),
        ],
    )
    def test_non_uz_numbers_are_kept(self, raw: str, expected: str) -> None:
        result = normalize_phone(raw)
        assert result.valid is True
        assert result.number == expected

    def test_country_code_reported(self) -> None:
        assert normalize_phone("+49 151 2345678").country_code == "49"


class TestInvalidInput:
    @pytest.mark.parametrize("raw", ["", None, "abc", "12345", "+", "+ 998", "nine one two"])
    def test_rejected(self, raw: str | None) -> None:
        result = normalize_phone(raw)
        assert result.valid is False
        assert result.number is None

    def test_too_long_is_rejected(self) -> None:
        assert normalize_phone("+9989012345678901234").valid is False

    def test_raw_value_is_preserved_for_auditing(self) -> None:
        result = normalize_phone("my phone is nine")
        assert result.raw == "my phone is nine"


class TestTextExtraction:
    def test_number_inside_a_sentence(self) -> None:
        result = extract_phone_from_text("Mening raqamim +998 90 123 45 67")
        assert result.valid is True
        assert result.number == "+998901234567"

    def test_no_number(self) -> None:
        assert extract_phone_from_text("yo'q").valid is False
