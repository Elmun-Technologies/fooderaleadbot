"""/link admin command: tracking deep-link generator."""

from __future__ import annotations

from app.handlers.admin import _sanitize_payload, format_tracking_link


def test_sanitize_payload_spaces_and_case() -> None:
    assert _sanitize_payload("TGAds Foodera Video01") == "tgads_foodera_video01"


def test_sanitize_payload_strips_junk() -> None:
    assert _sanitize_payload("  tgads  foodera!! uz#01 ") == "tgads_foodera_uz01"


def test_sanitize_payload_max_64() -> None:
    assert len(_sanitize_payload("a" * 200)) == 64


def test_link_built_with_bot_username() -> None:
    text = format_tracking_link("foodera_bot", "tgads foodera video01")
    assert "https://t.me/foodera_bot?start=tgads_foodera_video01" in text
    assert "Telegram Ads" in text
    assert "foodera" in text
    assert "video01" in text


def test_link_warns_on_unknown_source() -> None:
    text = format_tracking_link("foodera_bot", "somewhere foodera video01")
    assert "Unknown" in text
    assert "⚠️" in text


def test_link_without_args_shows_usage() -> None:
    text = format_tracking_link("foodera_bot", "")
    assert "/link" in text
    assert "t.me/foodera_bot?start=tgads_foodera_video01" in text
