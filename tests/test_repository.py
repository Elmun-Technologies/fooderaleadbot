"""Repository queries: draft handling, stats, funnel and source breakdowns."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.database.models import Classification, FunnelEvent, Lead, LeadStatus, LeadType
from app.database.repository import LeadRepository


async def make_lead(
    repo: LeadRepository,
    *,
    user_id: int,
    classification: str = Classification.WARM.value,
    completed: bool = True,
    lead_type: str = LeadType.EXHIBITOR.value,
    status: str = LeadStatus.NEW.value,
    campaign: str | None = "foodera",
    source: str = "telegram_ads",
    start_payload: str | None = "tgads_foodera_uz_01",
    created_at: datetime | None = None,
    **fields: object,
) -> Lead:
    lead = await repo.create_lead(
        lead_code_prefix="FD",
        telegram_user_id=user_id,
        language="uz",
        source=source,
        campaign=campaign,
        start_payload=start_payload,
        lead_type=lead_type,
        classification=classification,
        score=60,
        lead_status=status,
        company_name=fields.pop("company_name", "ACME FOOD"),
        **fields,
    )
    values: dict[str, object] = {"is_draft": not completed}
    if completed:
        values["completed_at"] = created_at or datetime.now(UTC)
    if created_at is not None:
        values["created_at"] = created_at
    updated = await repo.update_lead(lead.id, **values)
    return updated or lead


class TestLeadCodes:
    async def test_codes_are_unique_and_sequential(self, repo: LeadRepository) -> None:
        first = await repo.create_lead(lead_code_prefix="FD", telegram_user_id=1)
        second = await repo.create_lead(lead_code_prefix="FD", telegram_user_id=2)
        assert first.lead_code == "FD000001"
        assert second.lead_code == "FD000002"
        assert "PENDING" not in first.lead_code

    async def test_prefix_is_configurable(self, repo: LeadRepository) -> None:
        lead = await repo.create_lead(lead_code_prefix="XX", telegram_user_id=3)
        assert lead.lead_code.startswith("XX")

    async def test_find_lead_accepts_id_and_code(self, repo: LeadRepository) -> None:
        lead = await repo.create_lead(lead_code_prefix="FD", telegram_user_id=4)
        assert (await repo.find_lead(lead.id)).id == lead.id
        assert (await repo.find_lead(f"#{lead.lead_code}")).id == lead.id
        assert await repo.find_lead("FD9999999") is None


class TestUsers:
    async def test_get_or_create_is_idempotent(self, repo: LeadRepository) -> None:
        first = await repo.get_or_create_user(10, first_name="A")
        second = await repo.get_or_create_user(10, first_name="B", username="bb")
        assert first.id == second.id
        assert second.first_name == "B"
        assert second.username == "bb"

    async def test_defaults_only_apply_on_creation(self, repo: LeadRepository) -> None:
        await repo.get_or_create_user(11, defaults={"language": "ru"})
        again = await repo.get_or_create_user(11, defaults={"language": "uz"})
        assert again.language == "ru"


class TestDraftsAndAntiSpam:
    async def test_active_draft_only_returns_unfinished(self, repo: LeadRepository) -> None:
        await make_lead(repo, user_id=20, completed=False)
        draft = await repo.active_draft(20, ttl_hours=72)
        assert draft is not None and draft.is_draft is True

        await repo.update_lead(draft.id, completed_at=datetime.now(UTC), is_draft=False)
        assert await repo.active_draft(20, ttl_hours=72) is None
        assert await repo.recent_completed(20, within_hours=24) is not None

    async def test_recent_completed_respects_the_window(self, repo: LeadRepository) -> None:
        old = datetime.now(UTC) - timedelta(days=5)
        await make_lead(repo, user_id=21, created_at=old)
        assert await repo.recent_completed(21, within_hours=24) is None
        assert await repo.last_completed(21) is not None

    async def test_stale_drafts_are_listed(self, repo: LeadRepository) -> None:
        stale = await make_lead(repo, user_id=22, completed=False)
        await repo.update_lead(stale.id, updated_at=datetime.now(UTC) - timedelta(days=4))
        ids = [lead.id for lead in await repo.stale_drafts(older_than_hours=72)]
        assert stale.id in ids


class TestStatusFlow:
    async def test_compare_and_set_only_matches_the_expected_status(
        self, repo: LeadRepository
    ) -> None:
        lead = await make_lead(repo, user_id=30, status=LeadStatus.NEW.value)
        ok = await repo.mark_status_if_current(
            lead.id, LeadStatus.NEW.value, {"lead_status": LeadStatus.CONTACTED.value}
        )
        assert ok is True
        again = await repo.mark_status_if_current(
            lead.id, LeadStatus.NEW.value, {"lead_status": LeadStatus.BOOKED.value}
        )
        assert again is False
        fresh = await repo.get_lead(lead.id)
        assert fresh.lead_status == LeadStatus.CONTACTED.value

    async def test_set_status_records_the_manager(self, repo: LeadRepository) -> None:
        lead = await make_lead(repo, user_id=31)
        updated = await repo.set_status(
            lead.id, LeadStatus.BOOKED.value, manager_user_id=9, manager_username="m"
        )
        assert updated.lead_status == LeadStatus.BOOKED.value
        assert updated.manager_user_id == 9
        assert updated.status_changed_at is not None

    async def test_notification_reference_is_stored(self, repo: LeadRepository) -> None:
        lead = await make_lead(repo, user_id=32)
        await repo.attach_notification(lead.id, chat_id=-100500, message_id=77)
        fresh = await repo.get_lead(lead.id)
        assert (fresh.notify_chat_id, fresh.notify_message_id) == (-100500, 77)
        assert fresh.notified_at is not None


class TestFilters:
    async def test_list_leads_only_returns_completed_by_default(self, repo: LeadRepository) -> None:
        await make_lead(repo, user_id=40, completed=False)
        await make_lead(repo, user_id=41, completed=True)
        assert len(await repo.list_leads()) == 1
        assert len(await repo.list_leads(only_completed=False)) == 2

    async def test_classification_and_type_filters(self, repo: LeadRepository) -> None:
        await make_lead(repo, user_id=42, classification=Classification.HOT.value)
        await make_lead(repo, user_id=43, classification=Classification.COLD.value)
        await make_lead(
            repo,
            user_id=44,
            lead_type=LeadType.VISITOR.value,
            classification=Classification.VISITOR.value,
        )
        assert len(await repo.list_leads(classification=[Classification.HOT.value])) == 1
        assert len(await repo.list_leads(lead_type=LeadType.VISITOR.value)) == 1
        assert await repo.count_leads(classification=Classification.COLD.value) == 1

    async def test_since_filter_uses_created_at(self, repo: LeadRepository) -> None:
        old = datetime.now(UTC) - timedelta(days=3)
        await make_lead(repo, user_id=45, created_at=old)
        await make_lead(repo, user_id=46)
        since = datetime.now(UTC) - timedelta(hours=12)
        assert len(await repo.list_leads(since=since)) == 1


class TestStatistics:
    async def test_classification_counts_today_and_total(self, repo: LeadRepository) -> None:
        now = datetime.now(UTC)
        await make_lead(repo, user_id=50, classification=Classification.HOT.value)
        await make_lead(repo, user_id=51, classification=Classification.HOT.value)
        await make_lead(repo, user_id=52, classification=Classification.COLD.value)
        await make_lead(
            repo,
            user_id=53,
            classification=Classification.VISITOR.value,
            lead_type=LeadType.VISITOR.value,
        )
        await make_lead(
            repo,
            user_id=54,
            classification=Classification.WARM.value,
            created_at=now - timedelta(days=4),
        )

        total = await repo.classification_counts()
        assert total[Classification.HOT.value] == 2
        assert total[Classification.COLD.value] == 1
        assert total[Classification.WARM.value] == 1
        assert all(value >= 0 for value in total.values())

        today = await repo.classification_counts(since=now - timedelta(hours=12))
        assert today[Classification.WARM.value] == 0

        assert await repo.visitor_count() == 1

    async def test_status_counts(self, repo: LeadRepository) -> None:
        await make_lead(repo, user_id=60, status=LeadStatus.BOOKED.value)
        await make_lead(repo, user_id=61, status=LeadStatus.BOOKED.value)
        counts = await repo.status_counts()
        assert counts[LeadStatus.BOOKED.value] == 2
        assert set(counts) >= {status.value for status in LeadStatus}

    async def test_funnel_counts_unique_users(self, repo: LeadRepository) -> None:
        for user_id in (70, 71, 72):
            await repo.add_event(FunnelEvent.STARTED, telegram_user_id=user_id)
        for user_id in (70, 71):
            await repo.add_event(FunnelEvent.INTENT_SELECTED, telegram_user_id=user_id)
        await repo.add_event(FunnelEvent.COMPLETED, telegram_user_id=70)

        funnel = await repo.funnel_counts()
        assert funnel[FunnelEvent.STARTED.value] == 3
        assert funnel[FunnelEvent.INTENT_SELECTED.value] == 2
        assert funnel[FunnelEvent.COMPLETED.value] == 1
        assert await repo.started_count() == 3

    async def test_source_breakdown_groups_by_campaign(self, repo: LeadRepository) -> None:
        await make_lead(
            repo, user_id=80, campaign="foodera", classification=Classification.HOT.value
        )
        await make_lead(
            repo, user_id=81, campaign="foodera", classification=Classification.COLD.value
        )
        await make_lead(
            repo, user_id=82, campaign="autumn", source="qr", start_payload="qr_samarkand"
        )

        rows = {row["campaign"]: row for row in await repo.source_breakdown()}
        assert rows["foodera"]["total"] == 2
        assert rows["foodera"]["qualified"] == 1
        assert rows["foodera"]["completed"] == 2
        assert rows["autumn"]["total"] == 1

    async def test_payload_breakdown(self, repo: LeadRepository) -> None:
        await make_lead(
            repo,
            user_id=90,
            start_payload="tgads_foodera_uz_01",
            classification=Classification.WARM.value,
        )
        await make_lead(
            repo,
            user_id=91,
            start_payload="tgads_foodera_uz_01",
            classification=Classification.LOW.value,
        )
        rows = {row["start_payload"]: row for row in await repo.payload_breakdown()}
        assert rows["tgads_foodera_uz_01"]["total"] == 2
        assert rows["tgads_foodera_uz_01"]["qualified"] == 1

    async def test_average_score_excludes_visitors(self, repo: LeadRepository) -> None:
        await make_lead(repo, user_id=100, classification=Classification.WARM.value)
        await make_lead(
            repo,
            user_id=101,
            lead_type=LeadType.VISITOR.value,
            classification=Classification.VISITOR.value,
        )
        assert await repo.average_score() == 60.0

    async def test_stats_on_an_empty_database(self, repo: LeadRepository) -> None:
        assert await repo.count_leads() == 0
        assert await repo.visitor_count() == 0
        assert await repo.started_count() == 0
        assert await repo.average_score() == 0.0
        assert await repo.source_breakdown() == []
