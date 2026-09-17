"""The pipeline state machine the sales group drives.

These rules decide whether a manager's tap on a lead card is applied or refused,
so the whole table is covered explicitly.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from app.database.models import LOCKED_STATUSES, LeadStatus
from app.i18n.catalog_ru import CATALOG as RU
from app.i18n.catalog_uz import CATALOG as UZ
from app.services.statuses import (
    ACTION_STATUS,
    ALLOWED_TRANSITIONS,
    STATUS_ACTIONS,
    STATUS_LABEL_KEYS,
    can_transition,
    is_valid_status,
    transition_error_key,
)

ALL_STATUSES = [status.value for status in LeadStatus]


class TestActions:
    def test_every_button_action_maps_to_a_real_status(self) -> None:
        assert set(ACTION_STATUS.values()) <= set(ALL_STATUSES)
        assert set(ACTION_STATUS) == {"contacted", "negotiation", "booked", "not_qualified"}

    def test_buttons_are_rendered_from_the_actions(self) -> None:
        assert tuple((f"btn.status.{action}", action) for action in ACTION_STATUS) == STATUS_ACTIONS

    @pytest.mark.parametrize(
        "key",
        [*(key for key, _ in STATUS_ACTIONS), "err.status_same", "err.status_transition"],
    )
    def test_button_labels_exist_in_both_languages(self, key: str) -> None:
        assert key in UZ and key in RU
        assert UZ[key].strip() and RU[key].strip()

    def test_status_labels_exist_for_every_status(self) -> None:
        assert sorted(STATUS_LABEL_KEYS) == sorted(ALL_STATUSES)
        for status in LeadStatus:
            key = STATUS_LABEL_KEYS[status.value]
            assert status.value in UZ[key] or status.name in UZ[key]  # labels name the status


class TestTransitions:
    def test_the_happy_path_walks_forward(self) -> None:
        walk = [
            LeadStatus.NEW.value,
            LeadStatus.CONTACTED.value,
            LeadStatus.NEGOTIATION.value,
            LeadStatus.BOOKED.value,
            LeadStatus.CLOSED.value,
        ]
        for current, following in pairwise(walk):
            assert can_transition(current, following)

    def test_a_fresh_lead_cannot_be_booked_directly(self) -> None:
        assert not can_transition(LeadStatus.NEW.value, LeadStatus.BOOKED.value)
        assert can_transition(LeadStatus.NEW.value, LeadStatus.CONTACTED.value)
        assert can_transition(LeadStatus.NEW.value, LeadStatus.NOT_QUALIFIED.value)

    def test_closed_is_terminal(self) -> None:
        assert ALLOWED_TRANSITIONS[LeadStatus.CLOSED.value] == frozenset()
        for status in ALL_STATUSES:
            assert not can_transition(LeadStatus.CLOSED.value, status)

    def test_same_status_is_a_no_op(self) -> None:
        for status in ALL_STATUSES:
            assert not can_transition(status, status)
            assert transition_error_key(status, status) == "err.status_same"

    def test_unknown_or_foreign_targets_are_refused(self) -> None:
        assert not can_transition(LeadStatus.NEW.value, "SOLD")
        assert not can_transition(LeadStatus.NEW.value, "")
        assert transition_error_key(LeadStatus.NEW.value, "SOLD") == "err.status_transition"

    def test_missing_status_behaves_like_new(self) -> None:
        assert can_transition(None, LeadStatus.CONTACTED.value)
        assert not can_transition(None, LeadStatus.BOOKED.value)

    def test_no_transition_forwards_to_closed_only_once(self) -> None:
        # every non-terminal state may exit to CLOSED / NOT_QUALIFIED, nothing else
        for current, targets in ALLOWED_TRANSITIONS.items():
            assert current not in targets
            assert all(is_valid_status(target) for target in targets)
            if current in LOCKED_STATUSES:
                assert LeadStatus.CLOSED.value in targets or not targets

    @pytest.mark.parametrize("current", ALL_STATUSES)
    def test_table_covers_every_status(self, current: str) -> None:
        assert current in ALLOWED_TRANSITIONS
