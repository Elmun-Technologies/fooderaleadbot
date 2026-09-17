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
from app.options import Intent, OnlinePresence, Region, StandSize


def lead_dict(**values: object) -> dict[str, object]:
    base: dict[str, object] = {
        "intent": Intent.STAND,
        "online_presence": None,
        "region": None,
        "country": None,
        "website": None,
        "instagram": None,
    }
    base.update(values)
    return base


class TestPaths:
    def test_exhibitor_sees_all_ten_questions(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.STAND, online_presence=OnlinePresence.NONE))
        assert steps == [step for step in EXHIBITOR_PATH if step != "url"]
        assert len(steps) == 10

    def test_pricing_enquiry_also_gets_the_stand_question(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.PRICING, online_presence=OnlinePresence.NONE))
        assert "stand" in steps
        assert "readiness" in steps

    def test_partnership_skips_stand_size(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.PARTNER, online_presence=OnlinePresence.NONE))
        assert "stand" not in steps
        assert steps == [step for step in PARTNER_PATH if step != "url"]

    def test_visitor_gets_the_short_funnel_only(self) -> None:
        steps = steps_for(lead_dict(intent=Intent.VISITOR))
        assert steps == list(VISITOR_PATH)
        for forbidden in (
            "company_type",
            "category",
            "company_name",
            "stand",
            "readiness",
            "contact",
        ):
            assert forbidden not in steps

    def test_url_question_only_when_presence_claimed(self) -> None:
        without = steps_for(lead_dict(intent=Intent.STAND, online_presence=OnlinePresence.NONE))
        with_url = steps_for(lead_dict(intent=Intent.STAND, online_presence=OnlinePresence.BOTH))
        assert "url" not in without
        assert "url" in with_url

    def test_country_question_only_outside_uzbekistan(self) -> None:
        foreign = steps_for(
            lead_dict(
                intent=Intent.STAND, region=Region.FOREIGN, online_presence=OnlinePresence.NONE
            )
        )
        local = steps_for(
            lead_dict(
                intent=Intent.STAND, region=Region.SAMARKAND, online_presence=OnlinePresence.NONE
            )
        )
        assert foreign.index("country") == foreign.index("region") + 1
        assert "country" not in local

    def test_path_for_falls_back_to_exhibitor(self) -> None:
        assert path_for(None) == EXHIBITOR_PATH
        assert path_for("unknown-value") == EXHIBITOR_PATH


class TestNavigation:
    def test_next_step_sequence(self) -> None:
        lead = lead_dict(intent=Intent.STAND, online_presence=OnlinePresence.NONE)
        assert next_step("intent", lead) == "company_type"
        assert next_step("company_type", lead) == "category"
        assert next_step("readiness", lead) is None  # last question

    def test_back_from_the_first_question_is_not_possible(self) -> None:
        lead = lead_dict(intent=Intent.STAND)
        assert prev_step("intent", lead) is None
        assert prev_step("company_type", lead) == "intent"

    def test_back_steps_over_irrelevant_questions(self) -> None:
        lead = lead_dict(
            intent=Intent.STAND, online_presence=OnlinePresence.NONE, region=Region.SAMARKAND
        )
        # contact comes right after "online" because "url" was skipped
        assert prev_step("contact", lead) == "online"

    def test_next_step_after_region_for_foreign_lead(self) -> None:
        lead = lead_dict(
            intent=Intent.STAND, region=Region.FOREIGN, online_presence=OnlinePresence.NONE
        )
        assert next_step("region", lead) == "country"
        assert next_step("country", lead) == "online"

    def test_progress_counts_match_the_actual_path(self) -> None:
        lead = lead_dict(intent=Intent.STAND, online_presence=OnlinePresence.WEBSITE)
        assert progress_of("intent", lead) == (1, 11)
        assert progress_of("url", lead) == (7, 11)
        assert progress_of("readiness", lead) == (11, 11)

    def test_progress_for_visitor(self) -> None:
        lead = lead_dict(intent=Intent.VISITOR)
        assert progress_of("visitor_name", lead) == (2, 5)


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
        assert STEPS["url"].optional is True
        assert STEPS["company_name"].optional is False
        assert STEPS["intent"].optional is False

    def test_intent_is_first_and_cannot_go_back(self) -> None:
        assert STEPS["intent"].allow_back is False
        assert STEPS["intent"].kind is StepKind.INLINE

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
