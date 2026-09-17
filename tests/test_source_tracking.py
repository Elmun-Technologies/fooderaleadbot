"""Telegram Ads deep-link attribution parsing."""

from __future__ import annotations

import pytest
from app.services.source_tracking import SOURCE_LABELS, SourceInfo, parse_start_payload


class TestTelegramAdsPayloads:
    @pytest.mark.parametrize(
        ("payload", "source", "campaign", "creative"),
        [
            ("tgads_foodera_uz_01", "telegram_ads", "foodera", "uz_01"),
            ("tgads_foodera_ru_01", "telegram_ads", "foodera", "ru_01"),
            ("tgads_foodera_video01", "telegram_ads", "foodera", "video01"),
            ("tgads_foodera_distributor", "telegram_ads", "foodera", "distributor"),
            ("tgads_foodera_manufacturer", "telegram_ads", "foodera", "manufacturer"),
        ],
    )
    def test_documented_examples(
        self, payload: str, source: str, campaign: str, creative: str
    ) -> None:
        info = parse_start_payload(payload)
        assert info.source == source
        assert info.campaign == campaign
        assert info.creative == creative
        assert info.start_payload == payload
        assert info.parsed is True

    def test_long_creative_keeps_underscores(self) -> None:
        info = parse_start_payload("tgads_foodera_uz_video_autumn_launch")
        assert info.campaign == "foodera"
        assert info.creative == "uz_video_autumn_launch"

    def test_other_separators_are_accepted(self) -> None:
        for payload in ("tgads-foodera-uz-01", "tgads:foodera:uz:01", "tgads~foodera~uz~01"):
            info = parse_start_payload(payload)
            assert info.source == "telegram_ads"
            assert info.campaign == "foodera"
            assert info.start_payload == payload

    def test_case_insensitive(self) -> None:
        info = parse_start_payload("TGADS_FOODERA_UZ_01")
        assert info.source == "telegram_ads"
        assert info.campaign == "foodera"

    def test_source_labels_are_human_readable(self) -> None:
        assert parse_start_payload("tgads_foodera_uz_01").source_label == "Telegram Ads"
        assert SOURCE_LABELS["telegram_channel"] == "Telegram channel"


class TestOtherChannels:
    def test_channel_payload(self) -> None:
        # "_", "-", "~" and ":" are interchangeable separators
        info = parse_start_payload("channel_kiss-foodera_post12")
        assert info.source == "telegram_channel"
        assert info.campaign == "kiss"
        assert info.creative == "foodera_post12"

    def test_offline_qr(self) -> None:
        info = parse_start_payload("qr_samarqand_stand3")
        assert info.source == "qr"
        assert info.campaign == "samarqand"
        assert info.creative == "stand3"

    def test_partner(self) -> None:
        assert parse_start_payload("partner_assoc_uz").source == "partner"


class TestUnparsablePayloads:
    def test_single_token_is_kept_raw(self) -> None:
        info = parse_start_payload("foodera")
        assert info.parsed is False
        assert info.source == "unknown"
        assert info.start_payload == "foodera"
        assert info.campaign == "foodera"
        assert info.creative is None

    def test_garbage_is_kept_raw_but_never_used_as_a_field(self) -> None:
        info = parse_start_payload("!!!<script>alert(1)</script>")
        assert info.source == "unknown"
        assert info.parsed is False
        # the complete payload is preserved for the sales card (and escaped there),
        # while the structured fields only ever contain [a-z0-9_] tokens
        assert info.start_payload == "!!!<script>alert(1)</script>"[:120]
        assert info.campaign == "scriptalert1script"
        assert "<" not in str(info.campaign)

    def test_empty_and_none(self) -> None:
        assert parse_start_payload(None).source == "direct"
        assert parse_start_payload("").source == "direct"
        assert parse_start_payload("   ").source == "direct"

    def test_very_long_payload_is_truncated(self) -> None:
        info = parse_start_payload("tgads_" + "a" * 500)
        assert len(info.start_payload or "") <= 120

    def test_injection_attempt_never_reaches_a_query_field(self) -> None:
        info = parse_start_payload("tgads_foodera_uz'; DROP TABLE leads;--")
        assert info.source == "telegram_ads"
        assert info.campaign == "foodera"
        assert ";" not in (info.creative or "")
        assert "'" not in (info.creative or "")
        # the raw payload is kept verbatim (stored with bound parameters, escaped on output)
        assert "DROP TABLE leads" in (info.start_payload or "").replace("_", "_")


class TestLanguageHint:
    @pytest.mark.parametrize(
        ("payload", "hint"),
        [
            ("tgads_foodera_uz_01", "uz"),
            ("tgads_foodera_ru_01", "ru"),
            ("tgads_foodera_video01", None),
        ],
    )
    def test_hints(self, payload: str, hint: str | None) -> None:
        assert parse_start_payload(payload).language_hint == hint


class TestValueObject:
    def test_as_dict_shape(self) -> None:
        info = parse_start_payload("tgads_foodera_uz_01")
        assert info.as_dict() == {
            "start_payload": "tgads_foodera_uz_01",
            "source": "telegram_ads",
            "campaign": "foodera",
            "creative": "uz_01",
        }

    def test_is_paid_ads(self) -> None:
        assert SourceInfo(source="telegram_ads").is_paid_ads is True
        assert SourceInfo(source="qr").is_paid_ads is False
