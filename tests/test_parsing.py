"""Answer parsing: contact lines and links."""

from __future__ import annotations

import pytest
from app.services.parsing import (
    normalize_handle,
    normalize_website,
    parse_contact_line,
    split_links,
)


class TestContactLine:
    @pytest.mark.parametrize(
        ("raw", "name", "position"),
        [
            ("Azizbek — Savdo direktori", "Azizbek", "Savdo direktori"),
            ("Azizbek - Savdo direktori", "Azizbek", "Savdo direktori"),
            ("Azizbek Karimov / Director of Sales", "Azizbek Karimov", "Director of Sales"),
            ("Dilnoza, Marketing Manager", "Dilnoza", "Marketing Manager"),
            ("Igor: Kommercheskiy direktor", "Igor", "Kommercheskiy direktor"),
        ],
    )
    def test_name_and_position_are_split(self, raw: str, name: str, position: str) -> None:
        assert parse_contact_line(raw) == (name, position)

    def test_name_with_position_keyword_without_separator(self) -> None:
        name, position = parse_contact_line("Azizbek savdo direktori")
        assert name == "Azizbek"
        assert position and "direktori" in position

    def test_uncertain_input_keeps_the_raw_value_as_name(self) -> None:
        name, position = parse_contact_line("Azizbek Karimov")
        assert name == "Azizbek Karimov"
        assert position is None

    def test_empty(self) -> None:
        assert parse_contact_line("   ") == ("", None)

    def test_control_characters_are_stripped(self) -> None:
        name, position = parse_contact_line("Azizbek​ —\tSavdo direktori")
        assert name == "Azizbek"
        assert position == "Savdo direktori"


class TestLinks:
    def test_single_website(self) -> None:
        website, instagram = split_links("samarqandfood.uz")
        assert website == "samarqandfood.uz"
        assert instagram is None

    def test_website_with_scheme_and_www(self) -> None:
        website, _ = split_links("https://www.samarqandfood.uz/en")
        assert website == "samarqandfood.uz/en"

    def test_instagram_handle(self) -> None:
        website, instagram = split_links("@samarqand_food")
        assert instagram == "@samarqand_food"
        assert website is None

    def test_instagram_url(self) -> None:
        website, instagram = split_links("https://instagram.com/samarqand_food")
        assert instagram == "@samarqand_food"
        assert website is None

    def test_both_in_one_message(self) -> None:
        website, instagram = split_links("food.uz\n@samarqand_food")
        assert website == "food.uz"
        assert instagram == "@samarqand_food"

    def test_labeled_lines(self) -> None:
        website, instagram = split_links("sayt: samarqandfood.uz\ninstagram: @sf")
        assert website == "samarqandfood.uz"
        assert instagram == "@sf"

    def test_junk_is_not_a_link(self) -> None:
        website, instagram = split_links("no internet")
        assert website is None
        assert instagram is None


class TestHelpers:
    def test_normalize_handle_variants(self) -> None:
        for raw in ("@company", "company", "https://instagram.com/company/"):
            assert normalize_handle(raw) == "@company"

    def test_normalize_website_strips_scheme(self) -> None:
        assert normalize_website("http://www.acme.uz/") == "acme.uz"

    def test_instagram_in_website_slot_becomes_handle(self) -> None:
        assert normalize_website("instagram.com/acme") == "@acme"

    def test_long_values_are_clamped(self) -> None:
        assert len(parse_contact_line("A" * 400)[0]) <= 120

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_inputs(self, value: str | None) -> None:
        assert normalize_handle(value) is None
        assert normalize_website(value) is None
