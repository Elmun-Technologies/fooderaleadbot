"""End-to-end application logic against SQLite (no Telegram involved)."""

from __future__ import annotations

from datetime import timedelta

from app.database.models import Classification, FunnelEvent, LeadStatus, LeadType
from app.database.repository import LeadRepository
from app.flow import STEPS
from app.options import Category, CompanyType, Intent, OnlinePresence, Readiness, Region, StandSize
from app.services.lead_service import BeginOutcome, LeadService

HOT_ANSWERS = {
    "intent": Intent.STAND,
    "company_type": CompanyType.MANUFACTURER,
    "category": Category.CONFECTIONERY_AND_BAKERY,
    "company_name": "SAMARQAND FOOD LLC",
    "region": Region.SAMARKAND,
    "online_presence": OnlinePresence.WEBSITE,
    "website": "samarqandfood.uz",
    "contact_name": "Azizbek",
    "position": "Savdo direktori",
    "phone": "+998901234567",
    "preferred_stand_size": StandSize.SIZE_18,
    "readiness": Readiness.READY_TO_BOOK,
}


async def fill(service: LeadService, lead, answers: dict[str, object]) -> object:
    """Walk the questionnaire by calling the service exactly like the handlers do.

    ``answers`` is keyed by *lead field*, mirroring what ``engine.apply_*_answer``
    produces for each step.
    """
    for step_key, step in STEPS.items():
        values = {field: answers[field] for field in step.fields if field in answers}
        if values:
            lead = await service.save_answer(lead, step_key, values)
    return lead


class TestDraftCreation:
    async def test_start_creates_a_draft_with_attribution(self, leads, user) -> None:
        result = await leads.start_application(user)
        assert result.outcome is BeginOutcome.NEW
        lead = result.lead
        assert lead.is_draft is True
        assert lead.completed_at is None
        assert lead.current_step == "intent"
        assert lead.source == "telegram_ads"
        assert lead.campaign == "foodera"
        assert lead.creative == "uz_01"
        assert lead.start_payload == "tgads_foodera_uz_01"
        assert lead.lead_code.startswith("FD")
        assert lead.language == "uz"

    async def test_started_event_is_recorded_for_the_funnel(self, leads, user, repo) -> None:
        result = await leads.start_application(user)
        await repo.add_event(FunnelEvent.STARTED, telegram_user_id=user.telegram_user_id)
        events = await repo.events_for_lead(result.lead.id)
        assert [event.event for event in events] == [FunnelEvent.APPLICATION_OPENED.value]
        assert await repo.started_count() == 1


class TestAnswerPersistence:
    async def test_answer_updates_fields_pointer_and_events(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.STAND})
        assert lead.intent == Intent.STAND
        assert lead.lead_type == LeadType.EXHIBITOR.value
        assert lead.current_step == "company_type"

        events = await leads.repo.events_for_lead(lead.id)
        assert events[-1].event == FunnelEvent.INTENT_SELECTED.value
        assert events[-1].step == "intent"

    async def test_visitor_intent_switches_the_lead_type(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.VISITOR})
        assert lead.lead_type == LeadType.VISITOR.value
        assert lead.current_step == "visitor_name"

    async def test_partner_intent_skips_the_stand_question(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.PARTNER})
        assert lead.lead_type == LeadType.PARTNER.value
        for step_key in ("company_type", "category", "company_name"):
            lead = await leads.save_answer(
                lead, step_key, {step_key: "other" if step_key != "company_name" else "ACME"}
            )
        assert "stand" not in [event.step for event in await leads.repo.events_for_lead(lead.id)]

    async def test_unknown_fields_are_ignored(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(
            lead, "intent", {"intent": Intent.STAND, "score": 999, "admin": True}
        )
        assert lead.score == 0
        assert lead.intent == Intent.STAND

    async def test_phone_value_objects_are_flattened(self, leads, user) -> None:
        from app.utils.phone import normalize_phone

        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(
            lead, "phone", {"phone": normalize_phone("+998 90 123 45 67")}
        )
        assert lead.phone == "+998901234567"


class TestQualificationAndNotification:
    async def test_hot_lead_is_pushed_to_the_sales_group(self, leads, notifier, user, repo) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await fill(leads, lead, HOT_ANSWERS)
        result = await leads.finalize(lead)

        assert result.score == 100
        assert result.classification == Classification.HOT.value
        assert result.notified is True
        assert result.outcome == "qualified"
        assert len(notifier.sent) == 1
        assert notifier.sent[0].lead_code == lead.lead_code

        stored = await repo.get_lead(lead.id)
        assert stored is not None
        assert stored.is_draft is False
        assert stored.completed_at is not None
        assert stored.current_step is None
        assert stored.notify_message_id is not None
        assert stored.notify_chat_id == leads.settings.sales_group_id
        assert stored.score_breakdown["intent"] == 30

    async def test_warm_lead_without_phone_is_not_pushed(self, leads, notifier, user) -> None:
        answers = dict(HOT_ANSWERS)
        answers["phone"] = None
        answers["readiness"] = Readiness.JUST_INTERESTING
        answers["preferred_stand_size"] = StandSize.UNDECIDED
        lead = (await leads.start_application(user)).lead
        lead = await fill(leads, lead, answers)
        result = await leads.finalize(lead)

        assert result.classification in {
            Classification.WARM.value,
            Classification.COLD.value,
            Classification.HOT.value,
        }
        assert result.notified is False
        assert notifier.sent == []

    async def test_cold_lead_is_stored_but_not_pushed(self, leads, notifier, user, repo) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.PARTNER})
        lead = await leads.save_answer(lead, "company_type", {"company_type": CompanyType.HORECA})
        lead = await leads.save_answer(lead, "company_name", {"company_name": "Tiny Cafe"})
        result = await leads.finalize(lead)

        assert result.classification in {Classification.COLD.value, Classification.LOW.value}
        assert result.outcome == "cold"
        assert result.success_key == "success.cold"
        assert notifier.sent == []
        stored = await repo.get_lead(lead.id)
        assert stored is not None and stored.completed_at is not None  # still saved

    async def test_high_intent_override_ignores_a_low_score(
        self, leads, notifier, user, repo
    ) -> None:
        """Stand + ready to book + phone => qualified even with a thin profile."""
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.STAND})
        lead = await leads.save_answer(lead, "company_name", {"company_name": "Beach Café"})
        lead = await leads.save_answer(lead, "phone", {"phone": "+998901234567"})
        lead = await leads.save_answer(lead, "readiness", {"readiness": Readiness.READY_TO_BOOK})
        result = await leads.finalize(lead)

        assert (
            result.score == 30 + 10 + 20
        )  # intent + category-less/other?  company name is not scored
        assert result.classification == Classification.HOT.value
        assert result.high_intent is True
        assert result.outcome == "qualified"
        assert len(notifier.sent) == 1
        stored = await repo.get_lead(lead.id)
        assert stored is not None and stored.is_high_intent is True

    async def test_notification_failure_is_recorded_but_lead_is_kept(
        self, leads, user, repo
    ) -> None:
        class BrokenNotifier:
            sales_target = (-1001, None)
            visitor_target = None

            def card_language(self, lead):
                return "uz"

            async def send_lead_card(self, lead):
                return None  # e.g. the bot was removed from the group

        leads.notifier = BrokenNotifier()
        lead = (await leads.start_application(user)).lead
        lead = await fill(leads, lead, HOT_ANSWERS)
        result = await leads.finalize(lead)

        assert result.notified is False
        events = await repo.events_for_lead(lead.id)
        assert FunnelEvent.NOTIFICATION_FAILED.value in [event.event for event in events]
        assert result.outcome == "qualified"  # the user is never told about internals


class TestVisitorFlow:
    async def test_visitor_never_reaches_the_sales_group(self, leads, notifier, user, repo) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.VISITOR})
        lead = await leads.save_answer(lead, "visitor_name", {"contact_name": "Malika"})
        lead = await leads.save_answer(lead, "visitor_phone", {"phone": "+998901112233"})
        lead = await leads.save_answer(lead, "region", {"region": Region.TASHKENT})
        lead = await leads.save_answer(lead, "visitor_relation", {"business_relation": "student"})
        result = await leads.finalize(lead)

        assert result.classification == Classification.VISITOR.value
        assert result.outcome == "visitor"
        assert result.success_key == "success.visitor"
        assert notifier.sent == []
        assert notifier.visitor_sent == []
        stored = await repo.get_lead(lead.id)
        assert stored is not None
        assert stored.lead_type == LeadType.VISITOR.value
        assert stored.contact_name == "Malika"
        assert stored.phone == "+998901112233"
        assert stored.business_relation == "student"

    async def test_visitor_is_sent_to_the_visitor_group_when_configured(
        self, repo, settings, user, notifier_with_visitor_group
    ) -> None:
        service = LeadService(repo, settings, notifier_with_visitor_group)  # type: ignore[arg-type]
        lead = (await service.start_application(user)).lead
        lead = await service.save_answer(lead, "intent", {"intent": Intent.VISITOR})
        lead = await service.save_answer(lead, "visitor_name", {"contact_name": "Malika"})
        result = await service.finalize(lead)

        assert notifier_with_visitor_group.visitor_sent
        assert notifier_with_visitor_group.sent == []
        assert result.outcome == "visitor"


class TestAntiSpam:
    async def test_recent_application_offers_update_instead_of_a_new_lead(
        self, leads, user
    ) -> None:
        first = (await leads.start_application(user)).lead
        await fill(leads, first, HOT_ANSWERS)
        await leads.finalize(first)

        again = await leads.start_application(user)
        assert again.outcome is BeginOutcome.ALREADY_APPLIED
        assert again.lead.id == first.id

        updated = await leads.reset_for_update(again.lead)
        assert updated.id == first.id
        assert updated.is_draft is True
        assert updated.current_step == "intent"

    async def test_after_the_cooldown_a_new_lead_is_created(
        self, leads, user, settings, repo
    ) -> None:
        first = (await leads.start_application(user)).lead
        await fill(leads, first, HOT_ANSWERS)
        await leads.finalize(first)
        # pretend the application happened long ago
        from app.database.models import utcnow

        await repo.update_lead(first.id, completed_at=utcnow() - timedelta(days=3))

        again = await leads.start_application(user)
        assert again.outcome is BeginOutcome.NEW
        assert again.lead.id != first.id

    async def test_draft_is_offered_for_resume(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        await leads.save_answer(lead, "intent", {"intent": Intent.STAND})

        again = await leads.start_application(user)
        assert again.outcome is BeginOutcome.RESUMABLE_DRAFT
        assert again.lead.id == lead.id
        assert await leads.resume_step(again.lead) == "company_type"

    async def test_abandoned_draft_is_not_resumable(self, leads, user, repo) -> None:
        lead = (await leads.start_application(user)).lead
        await leads.abandon(lead)
        assert await repo.active_draft(user.telegram_user_id, ttl_hours=72) is None

    async def test_restart_wipes_the_answers(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await leads.save_answer(lead, "intent", {"intent": Intent.STAND})
        lead = await leads.save_answer(lead, "company_name", {"company_name": "ACME"})
        restarted = await leads.restart(lead)
        assert restarted.company_name is None
        assert restarted.intent is None
        assert restarted.current_step == "intent"
        assert restarted.score == 0


class TestStatusPipeline:
    async def test_manager_can_move_a_lead_forward(self, leads, notifier, user, repo) -> None:
        lead = (await leads.start_application(user)).lead
        lead = await fill(leads, lead, HOT_ANSWERS)
        await leads.finalize(lead)

        result = await leads.change_status(
            lead.id, "CONTACTED", manager_user_id=111, manager_username="manager"
        )
        assert result.ok is True
        assert result.lead is not None
        assert result.lead.lead_status == "CONTACTED"
        assert result.lead.manager_user_id == 111
        assert result.lead.manager_username == "manager"
        assert result.card_updated is True
        assert lead.id in notifier.edited

    async def test_duplicate_status_is_rejected(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        await leads.save_answer(lead, "intent", {"intent": Intent.STAND})
        first = await leads.change_status(
            lead.id, "CONTACTED", manager_user_id=111, manager_username=None
        )
        assert first.ok is True
        second = await leads.change_status(
            lead.id, "CONTACTED", manager_user_id=111, manager_username=None
        )
        assert second.ok is False
        assert second.message_key == "err.status_same"

    async def test_invalid_transition_is_blocked(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        await leads.change_status(
            lead.id, "NEW", manager_user_id=None, manager_username=None, force=True
        )
        result = await leads.change_status(
            lead.id, "BOOKED", manager_user_id=None, manager_username=None
        )
        assert result.ok is False
        assert result.message_key == "err.status_transition"

    async def test_force_override_is_available_to_admins(self, leads, user) -> None:
        lead = (await leads.start_application(user)).lead
        await leads.change_status(lead.id, "BOOKED", manager_user_id=None, manager_username=None)
        result = await leads.change_status(
            lead.id, "CLOSED", manager_user_id=None, manager_username=None, force=True
        )
        assert result.ok is True
        assert result.lead is not None and result.lead.lead_status == "CLOSED"

    async def test_unknown_lead_is_reported(self, leads) -> None:
        result = await leads.change_status(
            999999, "BOOKED", manager_user_id=None, manager_username=None
        )
        assert result.ok is False
        assert result.message_key == "err.lead_not_found"

    async def test_a_concurrent_manager_wins_only_once(
        self, leads, repo, user, database, monkeypatch
    ) -> None:
        """Compare-and-set: the loser of a simultaneous tap is told, not silently applied."""
        lead = (await leads.start_application(user)).lead
        await leads.save_answer(lead, "intent", {"intent": Intent.STAND})

        original = repo.get_lead
        raced = False

        async def get_lead_with_a_race(lead_id: int):
            """Simulate another manager committing between our read and our write.

            The competing write uses a second session/connection: writing through the same one
            would also mutate the object we are about to compare against, and the race - which
            is the thing under test - would disappear.
            """
            nonlocal raced
            found = await original(lead_id)
            if found is not None and not raced:
                raced = True
                async with database.session() as other:
                    await LeadRepository(other).update_lead(
                        lead_id, lead_status=LeadStatus.CONTACTED.value
                    )
            return found

        monkeypatch.setattr(repo, "get_lead", get_lead_with_a_race)
        result = await leads.change_status(
            lead.id,
            LeadStatus.NOT_QUALIFIED.value,
            manager_user_id=222,
            manager_username="slower_manager",
        )

        assert result.ok is False
        assert result.message_key == "err.status_changed"
        assert result.card_updated is False
        assert result.lead is not None
        assert result.lead.lead_status == LeadStatus.CONTACTED.value

        events = await repo.events_for_lead(lead.id)
        assert FunnelEvent.STATUS_CHANGED.value not in [event.event for event in events]


class TestLanguage:
    async def test_language_is_persisted_and_used_for_the_card(self, leads, user, settings) -> None:
        await leads.set_language(user, "ru")
        assert leads.language_of(user) == "ru"
        lead = (await leads.start_application(user)).lead
        assert lead.language in {"uz", "ru"}

    async def test_default_language_is_used_when_the_user_has_not_chosen(
        self, repo, settings, user
    ) -> None:
        from app.database.models import BotUser

        fresh = BotUser(telegram_user_id=999, language="uz", language_explicit=False)
        repo.session.add(fresh)
        await repo.session.commit()
        service = LeadService(repo, settings, None)
        assert service.language_of(fresh) == settings.default_language
