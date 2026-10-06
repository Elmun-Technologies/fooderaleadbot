"""Questionnaire flow: path selection, conditional steps, progress, navigation."""

from __future__ import annotations

import pytest
from app.flow import (
    EXHIBITOR_PATH,
    PARTNER_PATH,
    STEPS,
    VISITOR_PATH,
    StepError,
    StepKind,
    next_step,
    path_for,
    prev_step,
    progress_of,
    steps_for,
    validate_inline,
    validate_text,
)
from app.options import NEW_USER_INTENTS, Intent, Region, StandSize


def lead_dict(**values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "intent": Intent.STAND,
        "region": None,
        "country": None,
    }
    base.update(values)
    return base


class TestPaths:
    def test_exhibitor_sees_nine_questions(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.STAND))
        assert steps == list(EXHIBITOR_PATH)
        assert len(steps) == 9

    def test_no_online_or_links_question_any_more(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.STAND))
        for removed in ("online", "url"):
            assert removed not in steps
            assert removed not in STEPS

    def test_legacy_pricing_enquiry_still_gets_the_stand_question(self) -> None:
        """``pricing`` is no longer offered, but an old draft/callback must keep working."""
        steps = steps_for(lead_dict(intent=Intent.PRICING))
        assert steps == list(EXHIBITOR_PATH)
        assert "stand" in steps
        assert "readiness" in steps

    def test_legacy_partnership_skips_stand_size(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.PARTNER))
        assert "stand" not in steps
        assert steps == list(PARTNER_PATH)

    def test_visitor_gets_the_short_funnel_only(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.VISITOR))
        assert steps == list(VISITOR_PATH)
        assert steps == ["intent", "visitor_name", "visitor_phone", "visitor_region"]
        for forbidden in (
            "company_type",
            "category",
            "company_name",
            "stand",
            "readiness",
            "contact",
            "visitor_relation",
        ):
            assert forbidden not in steps

    def test_visitor_can_skip_the_phone(self) -> None:
        assert STEPS["visitor_phone"].optional is True

    def test_country_question_only_outside_uzbekistan(self) -> None:
        foreign = steps_for(lead_dict(intent=Intent.STAND, region=Region.FOREIGN))
        local = steps_for(lead_dict(intent=Intent.STAND, region=Region.SAMARKAND))
        assert foreign.index("country") == foreign.index("region") + 1
        assert "country" not in local

    def test_visitor_region_also_unlocks_the_country_question(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.VISITOR, region=Region.FOREIGN))
        assert steps == ["intent", "visitor_name", "visitor_phone", "visitor_region", "country"]

    def test_path_for_falls_back_to_exhibitor(self) -> None:
        assert path_for(None) == EXHIBITOR_PATH
        assert path_for("unknown-value") == EXHIBITOR_PATH


class TestNavigation:
    def test_next_step_sequence(self) -> None:
        lead = lead_dict(intent=Intent.STAND)
        assert next_step("intent", lead) == "company_type"
        assert next_step("company_type", lead) == "category"
        assert next_step("region", lead) == "contact"
        assert next_step("readiness", lead) is None  # last question

    def test_back_from_the_first_question_is_not_possible(self) -> None:
        lead = lead_dict(intent=Intent.STAND)
        assert prev_step("intent", lead) is None
        assert prev_step("company_type", lead) == "intent"

    def test_back_steps_over_irrelevant_questions(self) -> None:
        lead = lead_dict(intent=Intent.STAND, region=Region.SAMARKAND)
        assert prev_step("contact", lead) == "region"

    def test_next_step_after_region_for_foreign_lead(self) -> None:
        lead = lead_dict(intent=Intent.STAND, region=Region.FOREIGN)
        assert next_step("region", lead) == "country"
        assert next_step("country", lead) == "contact"

    def test_next_step_after_visitor_region(self) -> None:
        lead = lead_dict(intent=Intent.VISITOR, region=Region.FOREIGN)
        assert next_step("visitor_region", lead) == "country"
        assert next_step("country", lead) is None  # the visitor funnel ends here

    def test_progress_counts_match_the_actual_path(self) -> None:
        lead = lead_dict(intent=Intent.STAND)
        assert progress_of("intent", lead) == (1, 9)
        assert progress_of("contact", lead) == (6, 9)
        assert progress_of("readiness", lead) == (9, 9)

    def test_progress_for_visitor(self) -> None:
        lead = lead_dict(intent=Intent.VISITOR)
        assert progress_of("visitor_name", lead) == (2, 4)
        assert progress_of("visitor_region", lead) == (4, 4)


class TestStepDefinitions:
    def test_every_path_step_has_a_definition(self) -> None:
        for path in (EXHIBITOR_PATH, PARTNER_PATH, VISITOR_PATH):
            for key in path:
                assert key in STEPS, key

    def test_every_step_writes_at_least_one_field(self) -> None:
        for key, step in STEPS.items():
            assert step.fields, f"{key} writes nothing"
            assert step.question_key.startswith("q.")

    def test_optional_steps_are_the_only_skippable_ones(self) -> None:
        assert STEPS["phone"].optional is True
        assert STEPS["visitor_phone"].optional is True
        assert STEPS["company_name"].optional is False
        assert STEPS["intent"].optional is False

    def test_intent_is_first_and_cannot_go_back(self) -> None:
        assert STEPS["intent"].allow_back is False
        assert STEPS["intent"].kind is StepKind.INLINE

    def test_intent_offers_two_answers_to_new_users(self) -> None:
        assert STEPS["intent"].options == NEW_USER_INTENTS
        assert set(NEW_USER_INTENTS) == {"stand", "visitor"}

    def test_stand_sizes_are_the_documented_ones(self) -> None:
        assert {size.value for size in StandSize} == {
            "size_9",
            "size_18",
            "size_27",
            "size_36_plus",
            "undecided",
        }


class TestValidation:
    def test_inline_values_are_whitelisted(self) -> None:
        assert validate_inline("intent", Intent.STAND) == Intent.STAND
        with pytest.raises(StepError):
            validate_inline("intent", "everything")

    def test_legacy_intents_still_validate(self) -> None:
        """Old cards keep their buttons: the callback value must not become an error."""
        assert validate_inline("intent", Intent.PRICING) == Intent.PRICING
        assert validate_inline("intent", Intent.PARTNER) == Intent.PARTNER

    def test_text_limits(self) -> None:
        step = STEPS["company_name"]
        assert validate_text(step, "  Samarqand Food  ") == "Samarqand Food"
        with pytest.raises(StepError) as exc:
            validate_text(step, "a")
        assert exc.value.message_key == "err.company_name_len"

    def test_overlong_text_is_clamped_not_rejected(self) -> None:
        assert len(validate_text(STEPS["company_name"], "x" * 500)) == 120

    def test_control_and_zero_width_characters_are_stripped(self) -> None:
        cleaned = validate_text(STEPS["company_name"], "Fo\u200bo d\u0007d")
        assert "\u200b" not in cleaned
        assert "\x07" not in cleaned
        assert cleaned == "Foo dd"
