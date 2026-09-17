"""Lead pipeline statuses and the transitions managers may perform from the group.

Statuses: NEW → CONTACTED → NEGOTIATION → BOOKED, with NOT_QUALIFIED / CLOSED as exits.
The rules below are intentionally small and readable so the sales team can tune them.
"""

from __future__ import annotations

from app.database.models import LeadStatus

__all__ = [
    "ACTION_STATUS",
    "ALLOWED_TRANSITIONS",
    "STATUS_ACTIONS",
    "STATUS_LABEL_KEYS",
    "can_transition",
    "is_valid_status",
    "transition_error_key",
]

#: inline button callback suffix -> resulting status
ACTION_STATUS: dict[str, str] = {
    "contacted": LeadStatus.CONTACTED.value,
    "negotiation": LeadStatus.NEGOTIATION.value,
    "booked": LeadStatus.BOOKED.value,
    "not_qualified": LeadStatus.NOT_QUALIFIED.value,
}

#: (i18n key, action) pairs rendered as buttons on the lead card
STATUS_ACTIONS: tuple[tuple[str, str], ...] = tuple(
    (f"btn.status.{action}", action) for action in ACTION_STATUS
)

STATUS_LABEL_KEYS: dict[str, str] = {status.value: f"status.{status.name}" for status in LeadStatus}

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    LeadStatus.NEW.value: frozenset(
        {LeadStatus.CONTACTED.value, LeadStatus.NOT_QUALIFIED.value, LeadStatus.CLOSED.value}
    ),
    LeadStatus.CONTACTED.value: frozenset(
        {
            LeadStatus.NEGOTIATION.value,
            LeadStatus.BOOKED.value,
            LeadStatus.NOT_QUALIFIED.value,
            LeadStatus.CLOSED.value,
        }
    ),
    LeadStatus.NEGOTIATION.value: frozenset(
        {
            LeadStatus.BOOKED.value,
            LeadStatus.CONTACTED.value,
            LeadStatus.NOT_QUALIFIED.value,
            LeadStatus.CLOSED.value,
        }
    ),
    # a booking is only ever closed or (rarely) released
    LeadStatus.BOOKED.value: frozenset(
        {LeadStatus.NOT_QUALIFIED.value, LeadStatus.CLOSED.value, LeadStatus.NEGOTIATION.value}
    ),
    LeadStatus.NOT_QUALIFIED.value: frozenset(
        {LeadStatus.CONTACTED.value, LeadStatus.NEGOTIATION.value, LeadStatus.CLOSED.value}
    ),
    LeadStatus.CLOSED.value: frozenset(),
}


def is_valid_status(value: str | None) -> bool:
    return value in STATUS_LABEL_KEYS


def can_transition(current: str | None, new: str) -> bool:
    """Same status is a no-op (rejected); CLOSED is terminal."""
    if new not in STATUS_LABEL_KEYS:
        return False
    if current == new:
        return False
    return new in ALLOWED_TRANSITIONS.get(str(current or LeadStatus.NEW.value), frozenset())


def transition_error_key(current: str | None, new: str) -> str:
    return "err.status_same" if current == new else "err.status_transition"
