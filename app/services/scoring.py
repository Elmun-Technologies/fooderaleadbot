"""Deterministic lead scoring and qualification.

No AI, no randomness: two identical answers always produce the same score.  All
weights live in plain module-level dicts so a campaign manager can tune them in
minutes without touching the flow code.

Score is capped at :data:`MAX_SCORE` (100).

The simplified questionnaire no longer asks for a website / Instagram (or an online
presence at all): those legacy answers neither add nor remove points here.  Existing
rows keep the score that was stored when they were collected; a re-score simply does
not reward links any more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.options import (
    OTHER_VALUES,
    Category,
    CompanyType,
    Intent,
    Readiness,
    StandSize,
)

__all__ = [
    "CLASSIFICATION_RANK",
    "MAX_SCORE",
    "LeadAnswers",
    "ScoreResult",
    "classify",
    "is_high_intent",
    "score_lead",
    "should_send_to_sales_group",
]

MAX_SCORE = 100

#: real FOODERA directions (``other`` excluded - it scores CATEGORY_OTHER_SCORE)
_REAL_CATEGORIES: frozenset[str] = frozenset(
    value.value for value in Category if value.value not in OTHER_VALUES
)

# --------------------------------------------------------------------------- weights
INTENT_SCORES: dict[str, int] = {
    Intent.STAND: 30,
    Intent.PRICING: 25,
    Intent.PARTNER: 10,
    Intent.VISITOR: 0,
}

COMPANY_TYPE_SCORES: dict[str, int] = {
    CompanyType.MANUFACTURER: 20,
    CompanyType.INGREDIENT: 18,
    CompanyType.EQUIPMENT: 18,
    CompanyType.DISTRIBUTOR: 15,
    CompanyType.IMPORTER: 15,
    CompanyType.LOGISTICS: 12,
    CompanyType.RETAIL: 8,
    CompanyType.HORECA: 5,
    CompanyType.OTHER: 3,
}

#: any real FOODERA direction is worth the same, "other / unclear" less
CATEGORY_SCORE = 10
CATEGORY_OTHER_SCORE = 2

CONTACT_NAME_SCORE = 5
PHONE_SCORE = 10

STAND_SIZE_SCORES: dict[str, int] = {
    StandSize.SIZE_9: 4,
    StandSize.SIZE_18: 6,
    StandSize.SIZE_27: 8,
    StandSize.SIZE_36_PLUS: 10,
    StandSize.UNDECIDED: 2,
}

READINESS_SCORES: dict[str, int] = {
    Readiness.READY_TO_BOOK: 20,
    Readiness.REVIEW_OPTIONS: 15,
    Readiness.MANAGER_CALL: 10,
    Readiness.JUST_INTERESTING: 2,
}

#: statuses a lead can have after scoring
CLASSIFICATION_RANK: dict[str, int] = {"LOW": 0, "COLD": 1, "WARM": 2, "HOT": 3, "VISITOR": 0}


@dataclass(frozen=True)
class LeadAnswers:
    """Everything scoring needs to know about a lead (decoupled from the ORM)."""

    intent: str | None = None
    company_type: str | None = None
    category: str | None = None
    company_name: str | None = None
    region: str | None = None
    country: str | None = None
    contact_name: str | None = None
    position: str | None = None
    phone: str | None = None
    preferred_stand_size: str | None = None
    readiness: str | None = None
    source: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> LeadAnswers:
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in known})


@dataclass(frozen=True)
class ScoreResult:
    """Score plus the human readable breakdown (stored on the lead for audits)."""

    score: int
    high_intent: bool = False
    breakdown: list[tuple[str, int]] = field(default_factory=list)

    def breakdown_dict(self) -> dict[str, int]:
        return dict(self.breakdown)


def _has(value: Any) -> bool:
    return bool(str(value).strip()) if value is not None else False


def score_lead(answers: LeadAnswers) -> ScoreResult:
    """Score a lead. Pure function: same input -> same output, always."""
    breakdown: list[tuple[str, int]] = []

    def add(name: str, points: int) -> None:
        if points:
            breakdown.append((name, points))

    add("intent", INTENT_SCORES.get(str(answers.intent), 0))
    add("company_type", COMPANY_TYPE_SCORES.get(str(answers.company_type), 0))

    category = str(answers.category or "")
    if category and category in _REAL_CATEGORIES:
        add("category", CATEGORY_SCORE)
    elif category:  # "other" / anything that is not a FOODERA direction
        add("category", CATEGORY_OTHER_SCORE)

    if _has(answers.contact_name) and _has(answers.position):
        add("contact_quality", CONTACT_NAME_SCORE)
    if _has(answers.phone):
        add("phone", PHONE_SCORE)

    add("stand_size", STAND_SIZE_SCORES.get(str(answers.preferred_stand_size), 0))
    add("readiness", READINESS_SCORES.get(str(answers.readiness), 0))

    total = min(MAX_SCORE, sum(points for _, points in breakdown))
    return ScoreResult(score=total, high_intent=is_high_intent(answers), breakdown=breakdown)


def is_high_intent(answers: LeadAnswers) -> bool:
    """High priority override: stand intent + ready to book + reachable by phone."""
    return (
        answers.intent == Intent.STAND
        and answers.readiness == Readiness.READY_TO_BOOK
        and _has(answers.phone)
    )


def classify(
    score: int,
    *,
    intent: str | None,
    hot_min: int = 75,
    warm_min: int = 55,
    cold_min: int = 35,
    high_intent: bool = False,
) -> str:
    """Bucket the score.  Visitors are *always* VISITOR, whatever the score says."""
    if intent == Intent.VISITOR:
        return "VISITOR"
    if high_intent:
        # immediate qualification override
        return "HOT"
    if score >= hot_min:
        return "HOT"
    if score >= warm_min:
        return "WARM"
    if score >= cold_min:
        return "COLD"
    return "LOW"


def should_send_to_sales_group(
    answers: LeadAnswers,
    classification: str,
    *,
    high_intent: bool = False,
    min_classification: str = "WARM",
    require_phone: bool = True,
    require_company_name: bool = True,
) -> bool:
    """Qualification rule: hot/warm + phone + company name (thresholds configurable)."""
    if classification == "VISITOR":
        return False
    if not high_intent and CLASSIFICATION_RANK.get(classification, 0) < CLASSIFICATION_RANK.get(
        min_classification.upper(), 2
    ):
        return False
    required: list[object] = []
    if require_phone:
        required.append(answers.phone)
    if require_company_name:
        required.append(answers.company_name)
    return all(_has(value) for value in required)


def answers_from_lead(lead: Any) -> LeadAnswers:
    """Build :class:`LeadAnswers` from an ORM row or a plain dict of fields."""
    values = {
        name: (getattr(lead, name, None) if not isinstance(lead, dict) else lead.get(name))
        for name in LeadAnswers.__dataclass_fields__
    }
    return LeadAnswers(**values)
