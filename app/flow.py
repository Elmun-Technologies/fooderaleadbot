"""Flow definition: which questions exist, in which order, for whom.

The questionnaire is described declaratively in one place, which keeps the handlers
thin and makes Back / Skip / progress counters / resume-after-restart trivial:
``steps_for(lead)`` computes the concrete question list for a lead (conditional
questions such as ``country`` are inserted on demand), and navigation is just an
index lookup in that list.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from app.options import Intent, OnlinePresence, values_of

__all__ = [
    "EXHIBITOR_PATH",
    "FOREIGN_REGIONS",
    "PARTNER_PATH",
    "STEPS",
    "URL_PRESENCES",
    "VISITOR_PATH",
    "Step",
    "StepError",
    "StepKind",
    "next_step",
    "prev_step",
    "progress_of",
    "step_or_raise",
    "steps_for",
    "validate_inline",
    "validate_text",
]


class StepKind(StrEnum):
    INLINE = "inline"  # one option from an option group
    CATEGORY = "category"  # paginated option group
    TEXT = "text"  # free text, length validated
    URL = "url"  # website / instagram links
    PHONE = "phone"  # Telegram contact button or manual input


@dataclass(frozen=True)
class Step:
    key: str
    kind: StepKind
    question_key: str
    group: str | None = None  # option group (INLINE / CATEGORY)
    fields: tuple[str, ...] = ()  # lead fields written by this step
    hint_key: str | None = None
    error_key: str = "err.too_short"
    min_len: int | None = None
    max_len: int = 120
    columns: int = 1  # keyboard columns
    optional: bool = False  # user may skip it
    allow_back: bool = True  # "Back" button is offered
    per_row_labels: bool = True


def _step(key: str, kind: StepKind, question: str, **kwargs: object) -> Step:
    return Step(key=key, kind=kind, question_key=f"q.{question}", **kwargs)  # type: ignore[arg-type]


#: exhibitor funnel (Q1..Q10 of the specification)
EXHIBITOR_PATH: tuple[str, ...] = (
    "intent",
    "company_type",
    "category",
    "company_name",
    "region",
    "online",
    "url",
    "contact",
    "phone",
    "stand",
    "readiness",
)

#: partnership enquiries are real leads, but they do not buy a stand -> Q9 is skipped
PARTNER_PATH: tuple[str, ...] = tuple(key for key in EXHIBITOR_PATH if key != "stand")

#: visitors never see exhibitor questions
VISITOR_PATH: tuple[str, ...] = (
    "intent",
    "visitor_name",
    "visitor_phone",
    "region",
    "visitor_relation",
)

STEPS: dict[str, Step] = {
    step.key: step
    for step in (
        _step(
            "intent",
            StepKind.INLINE,
            "intent",
            group="intent",
            fields=("intent",),
            allow_back=False,
        ),
        _step(
            "company_type",
            StepKind.INLINE,
            "company_type",
            group="company_type",
            fields=("company_type",),
        ),
        _step(
            "category",
            StepKind.CATEGORY,
            "category",
            group="category",
            fields=("category",),
            columns=2,
            hint_key="hint.category",
        ),
        _step(
            "company_name",
            StepKind.TEXT,
            "company_name",
            fields=("company_name",),
            min_len=2,
            max_len=120,
            hint_key="hint.company_name",
            error_key="err.company_name_len",
        ),
        _step("region", StepKind.INLINE, "region", group="region", fields=("region",), columns=2),
        _step(
            "country",
            StepKind.TEXT,
            "country",
            fields=("country",),
            min_len=2,
            max_len=60,
            hint_key="hint.country",
            error_key="err.country_len",
        ),
        _step(
            "online",
            StepKind.INLINE,
            "online",
            group="online",
            fields=("online_presence",),
            columns=2,
        ),
        _step(
            "url",
            StepKind.URL,
            "url",
            fields=("website", "instagram"),
            optional=True,
            min_len=2,
            max_len=600,
            hint_key="hint.url",
            error_key="err.url_format",
        ),
        _step(
            "contact",
            StepKind.TEXT,
            "contact",
            fields=("contact_name", "position"),
            min_len=2,
            max_len=160,
            hint_key="hint.contact",
            error_key="err.contact_len",
        ),
        _step(
            "phone",
            StepKind.PHONE,
            "phone",
            fields=("phone",),
            optional=True,
            hint_key="hint.phone",
            error_key="err.phone_format",
        ),
        _step(
            "stand",
            StepKind.INLINE,
            "stand",
            group="stand",
            fields=("preferred_stand_size",),
            columns=2,
        ),
        _step("readiness", StepKind.INLINE, "readiness", group="readiness", fields=("readiness",)),
        _step(
            "visitor_name",
            StepKind.TEXT,
            "v_name",
            fields=("contact_name",),
            min_len=2,
            max_len=120,
            error_key="err.contact_len",
        ),
        _step(
            "visitor_phone",
            StepKind.PHONE,
            "v_phone",
            fields=("phone",),
            optional=True,
            hint_key="hint.phone",
            error_key="err.phone_format",
        ),
        _step(
            "visitor_relation",
            StepKind.INLINE,
            "v_relation",
            group="relation",
            fields=("business_relation",),
        ),
    )
}

#: online-presence answers that lead to the follow-up URL question
URL_PRESENCES: frozenset[str] = frozenset(
    {OnlinePresence.WEBSITE, OnlinePresence.INSTAGRAM, OnlinePresence.BOTH}
)

#: after this region we ask the follow-up "which country?" question
FOREIGN_REGIONS: frozenset[str] = frozenset({"foreign"})


def path_for(intent: str | None) -> tuple[str, ...]:
    """Base question sequence for a participation intent."""
    if intent == Intent.VISITOR:
        return VISITOR_PATH
    if intent == Intent.PARTNER:
        return PARTNER_PATH
    return EXHIBITOR_PATH


def steps_for(lead: Mapping[str, object]) -> list[str]:
    """Concrete question list for one lead, with conditional steps inserted."""
    intent = lead.get("intent")
    path = list(path_for(intent if isinstance(intent, str) else None))
    steps: list[str] = []
    for key in path:
        # an unanswered intent is treated as "stand", so the progress counter does not
        # jump on the very first question
        if key == "stand" and intent is not None and intent not in _stand_intents():
            continue
        if key == "url" and lead.get("online_presence") not in URL_PRESENCES:
            continue
        steps.append(key)
        if key == "region" and lead.get("region") in FOREIGN_REGIONS:
            steps.append("country")
    return steps


def _stand_intents() -> frozenset[str]:
    from app.options import EXHIBITOR_INTENTS

    return EXHIBITOR_INTENTS


def _position(step: str, steps: list[str]) -> int:
    try:
        return steps.index(step)
    except ValueError:
        return -1


def next_step(current: str, lead: Mapping[str, object]) -> str | None:
    steps = steps_for(lead)
    index = _position(current, steps)
    if index < 0:
        return steps[0] if steps else None
    if index + 1 < len(steps):
        return steps[index + 1]
    # conditional steps that only appear after the answer is saved
    if current == "region" and lead.get("region") in FOREIGN_REGIONS:
        return "country"
    if current == "online" and lead.get("online_presence") in URL_PRESENCES:
        return "url"
    return None


def prev_step(current: str, lead: Mapping[str, object]) -> str | None:
    steps = steps_for(lead)
    index = _position(current, steps)
    if index <= 0:
        return None
    return steps[index - 1]


def progress_of(current: str, lead: Mapping[str, object]) -> tuple[int, int]:
    """1-based ``(step_number, total)`` for the progress pill."""
    steps = steps_for(lead)
    index = _position(current, steps)
    total = len(steps)
    return (index + 1 if index >= 0 else 1, total or 1)


def first_unanswered_step(lead: Mapping[str, object]) -> str | None:
    """Used to resume a draft after a bot restart."""
    for key in steps_for(lead):
        step = STEPS[key]
        if step.fields and all(lead.get(field) in (None, "", []) for field in step.fields):
            return key
        if not step.fields:  # pragma: no cover - all steps write something
            return key
    return None


def step_or_raise(key: str | None) -> Step:
    if not key:
        raise StepError("err.no_active_form")
    try:
        return STEPS[key]
    except KeyError as exc:
        raise StepError("err.stale_callback") from exc


def is_known_option(group: str, value: str) -> bool:
    return value in values_of(group)


class StepError(ValueError):
    """A user answer failed validation; ``message_key`` is the i18n key to show."""

    def __init__(self, message_key: str, **context: object) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.context = context


def validate_inline(group: str, value: str) -> str:
    """Accept only values that belong to the option group (defence against forged callbacks)."""
    if not is_known_option(group, value):
        raise StepError("err.invalid_option")
    return value


def validate_text(step: Step, raw: str | None) -> str:
    """Normalise free text and enforce the configured length limits."""
    from app.utils.text import clean_text

    text = clean_text(raw, max_len=None)
    if step.min_len is not None and len(text) < step.min_len:
        raise StepError(step.error_key, min=step.min_len)
    if not text:
        raise StepError(step.error_key, min=step.min_len or 1)
    if len(text) > step.max_len:
        text = text[: step.max_len]
    return text
