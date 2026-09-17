"""Application logic: the only place that writes lead state.

Handlers stay thin (render the right question, parse the answer) and every
business decision - anti-spam, scoring, classification, qualification,
notification - is here, so it can be tested without Telegram.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.config import Settings
from app.database.models import BotUser, Classification, FunnelEvent, Lead, LeadType, utcnow
from app.database.repository import LeadRepository
from app.flow import STEPS, first_unanswered_step, next_step, steps_for
from app.i18n import normalize_language
from app.options import Intent
from app.services.notification import LeadNotifier
from app.services.scoring import (
    LeadAnswers,
    ScoreResult,
    classify,
    score_lead,
    should_send_to_sales_group,
)
from app.services.source_tracking import SourceInfo
from app.utils.phone import PhoneValue
from app.utils.text import clean_text

__all__ = ["BeginOutcome", "BeginResult", "FinalizeResult", "LeadService", "StatusResult"]

logger = logging.getLogger(__name__)

#: the ONLY lead fields the questionnaire may write.  Scores, statuses, attribution and
#: timestamps are owned by the services - a forged callback can never touch them.
QUESTION_FIELDS: frozenset[str] = frozenset(
    {
        "intent",
        "company_type",
        "category",
        "company_name",
        "region",
        "country",
        "online_presence",
        "website",
        "instagram",
        "contact_name",
        "position",
        "phone",
        "preferred_stand_size",
        "readiness",
        "business_relation",
        "lead_type",
    }
)


class BeginOutcome(StrEnum):
    NEW = "new"
    RESUMABLE_DRAFT = "draft"
    ALREADY_APPLIED = "already_applied"


@dataclass(frozen=True)
class BeginResult:
    lead: Lead
    outcome: BeginOutcome


@dataclass(frozen=True)
class FinalizeResult:
    """What the user is told after the questionnaire (never a verdict on them)."""

    lead: Lead
    outcome: str  # qualified | warm | cold | visitor
    classification: str
    score: int
    notified: bool
    high_intent: bool

    @property
    def success_key(self) -> str:
        return f"success.{self.outcome}"


@dataclass(frozen=True)
class StatusResult:
    ok: bool
    lead: Lead | None
    message_key: str | None = None
    card_updated: bool = False


class LeadService:
    def __init__(
        self,
        repository: LeadRepository,
        settings: Settings,
        notifier: LeadNotifier | None = None,
    ) -> None:
        self.repo = repository
        self.settings = settings
        self.notifier = notifier

    # ------------------------------------------------------------------ users
    async def ensure_user(
        self,
        telegram_user_id: int,
        *,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        telegram_language: str | None = None,
        source: SourceInfo | None = None,
    ) -> BotUser:
        """Create or refresh the profile, storing Telegram Ads attribution."""
        defaults: dict[str, Any] = {
            "language": self.settings.default_language,
            "language_explicit": False,
        }
        if source is not None:
            defaults.update(
                {
                    "start_payload": source.start_payload,
                    "source": source.source,
                    "campaign": source.campaign,
                    "creative": source.creative,
                }
            )
        user = await self.repo.get_or_create_user(
            telegram_user_id,
            username=clean_text(username, max_len=64) or None,
            first_name=clean_text(first_name, max_len=128) or None,
            last_name=clean_text(last_name, max_len=128) or None,
            defaults=defaults,
        )
        if (
            not user.language_explicit
            and not user.start_payload
            and source
            and source.start_payload
        ):
            await self.repo.update_user(
                user,
                start_payload=source.start_payload,
                source=source.source,
                campaign=source.campaign,
                creative=source.creative,
            )
        if not user.language:
            await self.repo.update_user(user, language=normalize_language(telegram_language))
        return user

    def language_of(self, user: BotUser | None) -> str:
        if user and user.language_explicit and normalize_language(user.language) in ("uz", "ru"):
            return normalize_language(user.language)
        return self.settings.default_language

    async def set_language(self, user: BotUser, language: str) -> BotUser:
        return await self.repo.update_user(
            user, language=normalize_language(language), language_explicit=True
        )

    async def update_attribution(self, user: BotUser, source: SourceInfo) -> BotUser:
        """A new deep link wins over an old one (the freshest campaign gets the lead)."""
        if not source.start_payload:
            return user
        return await self.repo.update_user(user, **source.as_dict())

    # ------------------------------------------------------------- applications
    async def start_application(self, user: BotUser, *, force_new: bool = False) -> BeginResult:
        """Open a draft lead, honouring the anti-spam rules."""
        telegram_user_id = user.telegram_user_id

        if not force_new:
            recent = await self.repo.recent_completed(
                telegram_user_id, within_hours=self.settings.recent_application_hours
            )
            if recent is not None:
                await self.repo.add_event(
                    FunnelEvent.ALREADY_APPLIED,
                    lead_id=recent.id,
                    telegram_user_id=telegram_user_id,
                    data={"lead_code": recent.lead_code},
                )
                return BeginResult(recent, BeginOutcome.ALREADY_APPLIED)

            draft = await self.repo.active_draft(
                telegram_user_id, ttl_hours=self.settings.draft_ttl_hours
            )
            if draft is not None:
                return BeginResult(draft, BeginOutcome.RESUMABLE_DRAFT)

        lead = await self._create_draft(user)
        return BeginResult(lead, BeginOutcome.NEW)

    async def open_new_draft(self, user: BotUser) -> Lead:
        """Public entry point used by the ``/start`` and "start over" buttons."""
        return await self._create_draft(user)

    async def _create_draft(self, user: BotUser) -> Lead:
        lead = await self.repo.create_lead(
            lead_code_prefix=self.settings.lead_code_prefix,
            bot_user_id=user.id,
            telegram_user_id=user.telegram_user_id,
            telegram_username=user.username,
            telegram_first_name=user.first_name,
            telegram_last_name=user.last_name,
            language=user.language or self.settings.default_language,
            start_payload=user.start_payload,
            source=user.source,
            campaign=user.campaign,
            creative=user.creative,
            lead_type=LeadType.EXHIBITOR.value,
            current_step="intent",
        )
        await self.repo.add_event(
            FunnelEvent.APPLICATION_OPENED,
            lead_id=lead.id,
            telegram_user_id=user.telegram_user_id,
            step="intent",
            data={"source": lead.source, "campaign": lead.campaign, "creative": lead.creative},
        )
        return lead

    async def reset_for_update(self, lead: Lead) -> Lead:
        """Re-open a finished application so the user can edit it (same lead code)."""
        updated = await self.repo.update_lead(
            lead.id,
            is_draft=True,
            current_step="intent",
            updated_at=utcnow(),
        )
        await self.repo.add_event(
            FunnelEvent.LEAD_UPDATED,
            lead_id=lead.id,
            telegram_user_id=lead.telegram_user_id,
            step="intent",
        )
        return updated or lead

    async def abandon(self, lead: Lead) -> None:
        await self.repo.abandon_draft(lead.id)
        await self.repo.add_event(
            FunnelEvent.ABANDONED, lead_id=lead.id, telegram_user_id=lead.telegram_user_id
        )

    async def restart(self, lead: Lead) -> Lead | None:
        """Wipe the answers of a draft and start from question 1."""
        return await self.repo.update_lead(
            lead.id,
            intent=None,
            company_type=None,
            category=None,
            company_name=None,
            region=None,
            country=None,
            online_presence=None,
            website=None,
            instagram=None,
            contact_name=None,
            position=None,
            phone=None,
            preferred_stand_size=None,
            readiness=None,
            business_relation=None,
            score=0,
            score_breakdown=None,
            classification=None,
            is_high_intent=False,
            completed_at=None,
            is_draft=True,
            current_step="intent",
            lead_type=LeadType.EXHIBITOR.value,
        )

    async def resume_step(self, lead: Lead) -> str:
        """Which question to show when a draft is resumed (after a restart, etc.)."""
        if lead.current_step and lead.current_step in STEPS:
            steps = steps_for(lead.field_values())
            if lead.current_step in steps:
                return lead.current_step
        return first_unanswered_step(lead.field_values()) or "intent"

    # ---------------------------------------------------------------- answers
    async def save_answer(
        self,
        lead: Lead,
        step_key: str,
        values: dict[str, Any],
        *,
        event: FunnelEvent | str | None = None,
    ) -> Lead:
        """Persist one answer, advance the pointer and log the funnel step."""
        values = {key: value for key, value in values.items() if key in QUESTION_FIELDS}
        extra: dict[str, Any] = {}

        if step_key == "intent":
            intent = str(values.get("intent") or "")
            extra["lead_type"] = self.lead_type_for_intent(intent)
        if isinstance(values.get("phone"), PhoneValue):
            values["phone"] = values["phone"].number or None

        updated = await self.repo.update_lead(lead.id, **values, **extra) or lead

        # pointer to the question the user still has to answer (used for resume)
        after = next_step(step_key, updated.field_values())
        await self.repo.update_lead(updated.id, current_step=after)
        updated.current_step = after

        await self.repo.add_event(
            event or self.default_event(step_key),
            lead_id=updated.id,
            telegram_user_id=updated.telegram_user_id,
            step=step_key,
            data={key: value for key, value in values.items() if value not in (None, "")},
        )
        return updated

    @staticmethod
    def lead_type_for_intent(intent: str | None) -> str:
        if intent == Intent.VISITOR:
            return LeadType.VISITOR.value
        if intent == Intent.PARTNER:
            return LeadType.PARTNER.value
        return LeadType.EXHIBITOR.value

    @staticmethod
    def default_event(step_key: str) -> str:
        return {
            "intent": FunnelEvent.INTENT_SELECTED.value,
            "company_type": FunnelEvent.COMPANY_TYPE_SELECTED.value,
            "category": FunnelEvent.CATEGORY_SELECTED.value,
            "company_name": FunnelEvent.COMPANY_ENTERED.value,
            "region": FunnelEvent.LOCATION_ENTERED.value,
            "country": FunnelEvent.LOCATION_ENTERED.value,
            "online": FunnelEvent.ONLINE_ENTERED.value,
            "url": FunnelEvent.ONLINE_ENTERED.value,
            "contact": FunnelEvent.CONTACT_ENTERED.value,
            "phone": FunnelEvent.PHONE_ENTERED.value,
            "stand": FunnelEvent.STAND_SELECTED.value,
            "readiness": FunnelEvent.READINESS_SELECTED.value,
            "visitor_name": FunnelEvent.CONTACT_ENTERED.value,
            "visitor_phone": FunnelEvent.PHONE_ENTERED.value,
            "visitor_relation": FunnelEvent.INTENT_SELECTED.value,
        }.get(step_key, step_key.upper())

    async def mark_skipped(self, lead: Lead, step_key: str) -> None:
        await self.repo.add_event(
            FunnelEvent.STEP_SKIPPED,
            lead_id=lead.id,
            telegram_user_id=lead.telegram_user_id,
            step=step_key,
        )

    # -------------------------------------------------------------- scoring
    def evaluate(self, lead: Lead) -> ScoreResult:
        answers = LeadAnswers.from_mapping(lead.field_values())
        return self._score(answers)

    def _score(self, answers: LeadAnswers) -> ScoreResult:
        return score_lead(answers)

    def classification_for(self, lead: Lead, result: ScoreResult) -> str:
        answers = LeadAnswers.from_mapping(lead.field_values())
        return classify(
            result.score,
            intent=answers.intent,
            hot_min=self.settings.hot_min_score,
            warm_min=self.settings.warm_min_score,
            cold_min=self.settings.cold_min_score,
            high_intent=result.high_intent,
        )

    def qualifies(self, lead: Lead, classification: str, high_intent: bool) -> bool:
        answers = LeadAnswers.from_mapping(lead.field_values())
        return should_send_to_sales_group(
            answers,
            classification,
            high_intent=high_intent,
            min_classification=self.settings.qualify_min_classification.upper(),
            require_phone=self.settings.require_phone_for_sales,
            require_company_name=self.settings.require_company_name_for_sales,
        )

    async def finalize(self, lead: Lead) -> FinalizeResult:
        """Score, classify, qualify and notify.  Called once, at the last question."""
        fresh = await self.repo.get_lead(lead.id) or lead
        answers = LeadAnswers.from_mapping(fresh.field_values())
        result = self._score(answers)
        classification = classify(
            result.score,
            intent=answers.intent,
            hot_min=self.settings.hot_min_score,
            warm_min=self.settings.warm_min_score,
            cold_min=self.settings.cold_min_score,
            high_intent=result.high_intent,
        )
        is_visitor = (
            str(fresh.lead_type) == LeadType.VISITOR.value
            or classification == Classification.VISITOR.value
        )
        send_to_sales = not is_visitor and self.qualifies(fresh, classification, result.high_intent)

        fresh = (
            await self.repo.update_lead(
                fresh.id,
                score=result.score,
                score_breakdown=result.breakdown_dict(),
                classification=classification,
                is_high_intent=result.high_intent,
                is_draft=False,
                completed_at=utcnow(),
                current_step=None,
                lead_status=fresh.lead_status or "NEW",
            )
            or fresh
        )

        await self.repo.add_event(
            FunnelEvent.COMPLETED,
            lead_id=fresh.id,
            telegram_user_id=fresh.telegram_user_id,
            data={
                "score": result.score,
                "classification": classification,
                "breakdown": result.breakdown_dict(),
                "sent_to_sales": send_to_sales,
            },
        )

        notified = False
        if self.notifier is not None:
            if send_to_sales:
                message = await self.notifier.send_lead_card(fresh)
                if message is not None:
                    notified = True
                    await self.repo.attach_notification(
                        fresh.id, chat_id=message.chat.id, message_id=message.message_id
                    )
                    await self.repo.add_event(
                        FunnelEvent.NOTIFICATION_SENT,
                        lead_id=fresh.id,
                        telegram_user_id=fresh.telegram_user_id,
                        data={"chat_id": message.chat.id, "classification": classification},
                    )
                else:
                    await self.repo.add_event(
                        FunnelEvent.NOTIFICATION_FAILED,
                        lead_id=fresh.id,
                        telegram_user_id=fresh.telegram_user_id,
                        data={"classification": classification},
                    )
            elif is_visitor and self.notifier.visitor_target is not None:
                message = await self.notifier.send_visitor_card(fresh)
                if message is not None:
                    notified = True
                    await self.repo.attach_notification(
                        fresh.id, chat_id=message.chat.id, message_id=message.message_id
                    )

        outcome = self.outcome_for(
            fresh, classification, send_to_sales, result.high_intent, is_visitor
        )
        logger.info(
            "lead completed",
            extra={
                "lead_code": fresh.lead_code,
                "score": result.score,
                "classification": classification,
                "outcome": outcome,
            },
        )
        return FinalizeResult(
            lead=fresh,
            outcome=outcome,
            classification=classification,
            score=result.score,
            notified=notified,
            high_intent=result.high_intent,
        )

    @staticmethod
    def outcome_for(
        lead: Lead, classification: str, sent_to_sales: bool, high_intent: bool, is_visitor: bool
    ) -> str:
        if is_visitor or classification == Classification.VISITOR.value:
            return "visitor"
        if not sent_to_sales:
            return "cold"
        if high_intent or classification == Classification.HOT.value:
            return "qualified"
        return "warm"

    # ------------------------------------------------------- status pipeline
    async def change_status(
        self,
        lead_id: int,
        new_status: str,
        *,
        manager_user_id: int | None,
        manager_username: str | None,
        force: bool = False,
    ) -> StatusResult:
        from app.services.statuses import can_transition

        lead = await self.repo.get_lead(lead_id)
        if lead is None:
            return StatusResult(False, None, "err.lead_not_found")

        current = str(lead.lead_status)
        if current == new_status:
            return StatusResult(False, lead, "err.status_same", card_updated=False)
        if not force and not can_transition(current, new_status):
            logger.info(
                "blocked status transition",
                extra={"lead_code": lead.lead_code, "from": current, "to": new_status},
            )
            return StatusResult(False, lead, "err.status_transition")

        # Compare-and-set on the status the transition was decided from: two managers
        # tapping the same card at the same moment must not both believe they won.
        changed = await self.repo.mark_status_if_current(
            lead_id,
            expected=current,
            values={
                "lead_status": new_status,
                "manager_user_id": manager_user_id,
                "manager_username": manager_username,
                "status_changed_at": utcnow(),
            },
        )
        if not changed:
            loser = await self.repo.get_lead(lead_id)
            logger.info(
                "status change lost the race",
                extra={"lead_code": lead.lead_code, "attempted": new_status},
            )
            return StatusResult(False, loser, "err.status_changed", card_updated=False)

        updated = await self.repo.get_lead(lead_id)
        if updated is None:  # pragma: no cover - deleted between the two queries
            return StatusResult(False, None, "err.lead_not_found")

        await self.repo.add_event(
            FunnelEvent.STATUS_CHANGED,
            lead_id=lead_id,
            telegram_user_id=lead.telegram_user_id,
            data={"from": current, "to": new_status, "manager": manager_user_id},
        )

        card_updated = False
        if self.notifier is not None:
            card_updated = await self.notifier.update_lead_card(updated)
            if new_status == "CLOSED":
                await self.notifier.lock_card(updated, "📁 CLOSED")
        return StatusResult(True, updated, None, card_updated=card_updated)
