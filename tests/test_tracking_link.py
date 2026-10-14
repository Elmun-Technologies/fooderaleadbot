"""Named tracking links: slug generation, DB lookups, /start attribution, stats."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.database.models import Classification
from app.database.repository import LeadRepository
from app.services.tracking_links import (
    build_deep_link,
    detect_source,
    resolve_source,
    slugify,
    unique_payload,
)
from app.web.routers.links import _matches_stage


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


class TestTrackingLinkPeople:
    """The per-link breakdown: one row per person plus the stage they reached."""

    async def test_start_draft_and_completed_stages(self, repo: LeadRepository) -> None:
        await repo.create_tracking_link(
            title="Instagram dekabr", payload="instagram_dekabr", source="instagram"
        )
        # 1) only pressed /start
        await repo.get_or_create_user(
            telegram_user_id=201,
            username="sardor",
            first_name="Sardor",
            defaults={"start_payload": "instagram_dekabr"},
        )
        # 2) started the questionnaire but left it unfinished
        await repo.get_or_create_user(
            telegram_user_id=202,
            username="nodira",
            first_name="Nodira",
            defaults={"start_payload": "instagram_dekabr"},
        )
        draft = await repo.create_lead(
            lead_code_prefix="FD",
            telegram_user_id=202,
            telegram_username="nodira",
            start_payload="instagram_dekabr",
            current_step="company",
        )
        # 3) filled everything in and came out HOT
        await repo.get_or_create_user(
            telegram_user_id=203,
            username="bekzod",
            first_name="Bekzod",
            defaults={"start_payload": "instagram_dekabr"},
        )
        completed = await repo.create_lead(
            lead_code_prefix="FD",
            telegram_user_id=203,
            telegram_username="bekzod",
            start_payload="instagram_dekabr",
            contact_name="Bekzod Karimov",
            phone="+998901234567",
            classification=Classification.HOT.value,
        )
        await repo.update_lead(
            completed.id, completed_at=datetime.now(UTC), is_draft=False, current_step=None
        )

        people = await repo.tracking_link_people("instagram_dekabr")

        # newest first, one row per person
        assert [row["telegram_user_id"] for row in people] == [203, 202, 201]
        by_id = {row["telegram_user_id"]: row for row in people}

        assert by_id[201]["stage"] == "started"
        assert by_id[201]["lead"] is None
        assert by_id[201]["name"] == "Sardor"
        assert by_id[201]["username"] == "sardor"
        assert by_id[201]["first_seen"] is not None

        assert by_id[202]["stage"] == "draft"
        assert by_id[202]["lead"] is not None and by_id[202]["lead"].id == draft.id

        assert by_id[203]["stage"] == "completed"
        assert by_id[203]["lead"] is not None and by_id[203]["lead"].id == completed.id
        # the finished row still carries the answers the managers need
        assert by_id[203]["lead"].phone == "+998901234567"
        assert by_id[203]["lead"].classification == Classification.HOT.value

    async def test_newest_lead_wins_when_a_person_has_several(self, repo: LeadRepository) -> None:
        await repo.create_tracking_link(title="QR banner", payload="qr_banner", source="qr")
        first = await repo.create_lead(
            lead_code_prefix="FD",
            telegram_user_id=301,
            telegram_username="dilnoza",
            telegram_first_name="Dilnoza",
            start_payload="qr_banner",
        )
        second = await repo.create_lead(
            lead_code_prefix="FD",
            telegram_user_id=301,
            telegram_username="dilnoza",
            telegram_first_name="Dilnoza",
            start_payload="qr_banner",
            classification=Classification.WARM.value,
        )
        await repo.update_lead(second.id, completed_at=datetime.now(UTC), is_draft=False)

        people = await repo.tracking_link_people("qr_banner")

        assert first.id != second.id
        assert len(people) == 1
        row = people[0]
        assert row["telegram_user_id"] == 301
        assert row["stage"] == "completed"
        assert row["lead"] is not None and row["lead"].id == second.id
        assert row["name"] == "Dilnoza"  # no bot_users row -> falls back to the lead
        assert row["username"] == "dilnoza"

    async def test_empty_link_returns_nothing(self, repo: LeadRepository) -> None:
        await repo.create_tracking_link(title="Bo'sh link", payload="bosh_link", source="other")
        # traffic from another link must not leak into this one
        await repo.get_or_create_user(
            telegram_user_id=401,
            defaults={"start_payload": "boshqa_link"},
        )
        await repo.create_lead(
            lead_code_prefix="FD",
            telegram_user_id=401,
            start_payload="boshqa_link",
            classification=Classification.HOT.value,
        )

        assert await repo.tracking_link_people("bosh_link") == []
        assert await repo.tracking_link_people("umuman_yoq") == []


class TestLinkStageFilters:
    """The funnel cards on /admin/links/<id> filter the table with the same rules."""

    @staticmethod
    def _person(stage: str, *, classification: str | None = None, status: str = "NEW"):
        lead = (
            None
            if stage == "started"
            else SimpleNamespace(classification=classification, lead_status=status)
        )
        return {"stage": stage, "lead": lead}

    def test_a_stage_card_matches_its_own_stage_only(self) -> None:
        started = self._person("started")
        assert _matches_stage(started, "started")
        assert not _matches_stage(started, "draft")
        assert not _matches_stage(started, "completed")
        assert not _matches_stage(started, "qualified")
        assert not _matches_stage(started, "booked")

    def test_qualified_card_counts_hot_and_warm(self) -> None:
        assert _matches_stage(self._person("completed", classification="HOT"), "qualified")
        assert _matches_stage(self._person("completed", classification="WARM"), "qualified")
        assert not _matches_stage(self._person("draft", classification="COLD"), "qualified")

    def test_booked_card_needs_the_pipeline_status(self) -> None:
        booked = self._person("completed", classification="HOT", status="BOOKED")
        assert _matches_stage(booked, "booked")
        assert not _matches_stage(self._person("completed", classification="HOT"), "booked")


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
