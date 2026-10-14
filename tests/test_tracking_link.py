"""Named tracking links: slug generation, DB lookups, /start attribution, stats."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database.models import Classification
from app.database.repository import LeadRepository
from app.services.tracking_links import (
    build_deep_link,
    detect_source,
    resolve_source,
    slugify,
    unique_payload,
)


class TestSlugify:
    def test_spaces_and_case(self) -> None:
        assert slugify("Instagram Dekabr Aksiyasi") == "instagram_dekabr_aksiyasi"

    def test_uzbek_apostrophes(self) -> None:
        assert slugify("Yangi yil o'yin") == "yangi_yil_oyin"

    def test_cyrillic_transliterated(self) -> None:
        assert slugify("Новый год акция") == "noviy_god_aktsiya"

    def test_junk_removed(self) -> None:
        assert slugify("  QR — banner!!! #3 ") == "qr_banner_3"

    def test_max_64_chars(self) -> None:
        assert len(slugify("a b" * 100)) <= 64

    def test_empty(self) -> None:
        assert slugify("!!!") == ""


class TestUniquePayload:
    def test_free_name_kept(self) -> None:
        assert unique_payload("instagram_dekabr", set()) == "instagram_dekabr"

    def test_collision_gets_suffix(self) -> None:
        taken = {"instagram_dekabr", "instagram_dekabr_2"}
        assert unique_payload("instagram_dekabr", taken) == "instagram_dekabr_3"


class TestDetectSource:
    def test_instagram(self) -> None:
        assert detect_source("Instagram dekabr stories") == "instagram"

    def test_channel(self) -> None:
        assert detect_source("Kanal post yangi yil") == "telegram_channel"

    def test_ads(self) -> None:
        assert detect_source("TGAds dekabr") == "telegram_ads"

    def test_qr(self) -> None:
        assert detect_source("QR banner expo") == "qr"

    def test_unknown_is_other(self) -> None:
        assert detect_source("Yangi yil aksiyasi") == "other"


def test_build_deep_link() -> None:
    assert (
        build_deep_link("@foodera_bot", "instagram_dekabr")
        == "https://t.me/foodera_bot?start=instagram_dekabr"
    )


class TestRepositoryLinks:
    async def test_create_and_lookup(self, repo: LeadRepository) -> None:
        link = await repo.create_tracking_link(
            title="Instagram dekabr", payload="instagram_dekabr", source="instagram"
        )
        found = await repo.tracking_link_by_payload("instagram_dekabr")
        assert found is not None and found.id == link.id
        assert await repo.tracking_link_by_payload("nope") is None
        assert await repo.tracking_payloads() == {"instagram_dekabr"}

    async def test_delete(self, repo: LeadRepository) -> None:
        link = await repo.create_tracking_link(title="X", payload="x", source="other")
        assert await repo.delete_tracking_link(link.id) is True
        assert await repo.delete_tracking_link(link.id) is False
        assert await repo.tracking_link_by_payload("x") is None

    async def test_stats_count_starts_leads_qualified(self, repo: LeadRepository) -> None:
        await repo.create_tracking_link(
            title="Instagram dekabr", payload="instagram_dekabr", source="instagram"
        )
        # two users pressed start through the link
        for uid in (101, 102):
            await repo.get_or_create_user(
                telegram_user_id=uid,
                defaults={"start_payload": "instagram_dekabr", "source": "instagram"},
            )
        # one of them completed a HOT application
        lead = await repo.create_lead(
            lead_code_prefix="FD",
            telegram_user_id=101,
            start_payload="instagram_dekabr",
            source="instagram",
            classification=Classification.HOT.value,
        )
        await repo.update_lead(lead.id, completed_at=datetime.now(UTC), is_draft=False)

        rows = await repo.tracking_link_stats()
        assert len(rows) == 1
        row = rows[0]
        assert row["title"] == "Instagram dekabr"
        assert row["starts"] == 2
        assert row["leads"] == 1
        assert row["qualified"] == 1


class TestResolveSource:
    async def test_saved_link_wins_over_parsing(self, repo: LeadRepository) -> None:
        await repo.create_tracking_link(
            title="Yangi yil aksiyasi", payload="yangi_yil_aksiyasi", source="instagram"
        )
        info = await resolve_source(repo, "yangi_yil_aksiyasi")
        assert info.source == "instagram"
        assert info.campaign == "yangi_yil_aksiyasi"
        assert info.start_payload == "yangi_yil_aksiyasi"

    async def test_unknown_payload_falls_back_to_parser(self, repo: LeadRepository) -> None:
        info = await resolve_source(repo, "tgads_foodera_uz_01")
        assert info.source == "telegram_ads"
        assert info.campaign == "foodera"

    async def test_no_payload_is_direct(self, repo: LeadRepository) -> None:
        info = await resolve_source(repo, None)
        assert info.source == "direct"
