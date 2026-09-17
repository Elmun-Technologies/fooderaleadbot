"""Scoring rules from the specification, asserted one block at a time."""

from __future__ import annotations

import pytest
from app.options import Category, CompanyType, Intent, Readiness, StandSize
from app.services.scoring import (
    MAX_SCORE,
    LeadAnswers,
    classify,
    is_high_intent,
    score_lead,
    should_send_to_sales_group,
)


def base(**overrides: object) -> LeadAnswers:
    answers = {
        "intent": Intent.STAND,
        "company_type": CompanyType.MANUFACTURER,
        "category": Category.CONFECTIONERY_AND_BAKERY,
        "company_name": "SAMARQAND FOOD LLC",
        "contact_name": "Azizbek",
        "position": "Savdo direktori",
        "phone": "+998901234567",
        "website": "samarqandfood.uz",
        "preferred_stand_size": StandSize.SIZE_18,
        "readiness": Readiness.REVIEW_OPTIONS,
    }
    answers.update(overrides)
    return LeadAnswers(**answers)  # type: ignore[arg-type]


class TestIntentWeights:
    @pytest.mark.parametrize(
        ("intent", "points"),
        [
            (Intent.STAND, 30),
            (Intent.PRICING, 25),
            (Intent.PARTNER, 10),
            (Intent.VISITOR, 0),
        ],
    )
    def test_intent_scores(self, intent: str, points: int) -> None:
        minimal = LeadAnswers(intent=intent)
        assert score_lead(minimal).score == points


class TestCompanyTypeWeights:
    @pytest.mark.parametrize(
        ("company_type", "points"),
        [
            (CompanyType.MANUFACTURER, 20),
            (CompanyType.INGREDIENT, 18),
            (CompanyType.EQUIPMENT, 18),
            (CompanyType.DISTRIBUTOR, 15),
            (CompanyType.IMPORTER, 15),
            (CompanyType.LOGISTICS, 12),
            (CompanyType.RETAIL, 8),
            (CompanyType.HORECA, 5),
            (CompanyType.OTHER, 3),
        ],
    )
    def test_company_type_scores(self, company_type: str, points: int) -> None:
        assert score_lead(LeadAnswers(company_type=company_type)).score == points


class TestCategoryVerificationContactStandReadiness:
    def test_valid_category_is_10_other_is_2(self) -> None:
        assert score_lead(LeadAnswers(category=Category.DAIRY_AND_CHEESE)).score == 10
        assert score_lead(LeadAnswers(category=Category.OTHER)).score == 2
        assert score_lead(LeadAnswers(category=None)).score == 0

    def test_online_presence(self) -> None:
        assert score_lead(LeadAnswers(website="site.uz")).score == 8
        assert score_lead(LeadAnswers(instagram="@site")).score == 8
        assert score_lead(LeadAnswers(website="site.uz", instagram="@site")).score == 10
        assert score_lead(LeadAnswers()).score == 0

    def test_whitespace_only_links_do_not_count(self) -> None:
        assert score_lead(LeadAnswers(website="   ", instagram=" ")).score == 0

    def test_contact_name_plus_position_and_phone(self) -> None:
        assert score_lead(LeadAnswers(contact_name="Aziz", position="Direktor")).score == 5
        assert score_lead(LeadAnswers(contact_name="Aziz")).score == 0  # position missing
        assert score_lead(LeadAnswers(phone="+998901234567")).score == 10

    @pytest.mark.parametrize(
        ("size", "points"),
        [
            (StandSize.SIZE_9, 4),
            (StandSize.SIZE_18, 6),
            (StandSize.SIZE_27, 8),
            (StandSize.SIZE_36_PLUS, 10),
            (StandSize.UNDECIDED, 2),
        ],
    )
    def test_stand_sizes(self, size: str, points: int) -> None:
        assert score_lead(LeadAnswers(preferred_stand_size=size)).score == points

    @pytest.mark.parametrize(
        ("readiness", "points"),
        [
            (Readiness.READY_TO_BOOK, 20),
            (Readiness.REVIEW_OPTIONS, 15),
            (Readiness.MANAGER_CALL, 10),
            (Readiness.JUST_INTERESTING, 2),
        ],
    )
    def test_readiness(self, readiness: str, points: int) -> None:
        assert score_lead(LeadAnswers(readiness=readiness)).score == points


class TestFullLead:
    def test_exhibitor_profile_sums_exactly_as_documented(self) -> None:
        """30 + 20 + 10 + 8 + 5 + 10 + 6 + 15 = 104 -> capped to 100."""
        result = score_lead(base())
        assert result.breakdown_dict() == {
            "intent": 30,
            "company_type": 20,
            "category": 10,
            "verification": 8,
            "contact_quality": 5,
            "phone": 10,
            "stand_size": 6,
            "readiness": 15,
        }
        assert result.score == MAX_SCORE

    def test_max_score_is_capped(self) -> None:
        loudest_possible = LeadAnswers(
            intent=Intent.STAND,
            company_type=CompanyType.MANUFACTURER,
            category=Category.FISH_AND_SEAFOOD,
            website="a.uz",
            instagram="@a",
            contact_name="A",
            position="B",
            phone="+998901234567",
            preferred_stand_size=StandSize.SIZE_36_PLUS,
            readiness=Readiness.READY_TO_BOOK,
        )
        raw_sum = 30 + 20 + 10 + 10 + 5 + 10 + 10 + 20  # 115
        assert raw_sum > MAX_SCORE
        assert score_lead(loudest_possible).score == MAX_SCORE

    def test_breakdown_is_returned_for_audit(self) -> None:
        result = score_lead(base())
        assert "company_type" in result.breakdown_dict()
        assert sum(result.breakdown_dict().values()) >= result.score

    def test_scoring_is_deterministic(self) -> None:
        assert score_lead(base()).score == score_lead(base()).score


class TestUnknownValuesAreSafe:
    def test_forged_values_cannot_inflate_the_score(self) -> None:
        result = score_lead(
            LeadAnswers(
                intent="hacked",
                company_type="hacked",
                category="hacked",
                preferred_stand_size="hacked",
                readiness="hacked",
            )
        )
        # unknown category is treated like "other": +2, nothing else counts
        assert result.score == 2

    def test_other_category_scores_two(self) -> None:
        assert score_lead(LeadAnswers(category=Category.OTHER)).score == 2

    def test_missing_answers_score_zero(self) -> None:
        assert score_lead(LeadAnswers()).score == 0
        assert score_lead(LeadAnswers()).breakdown == []


class TestClassification:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (100, "HOT"),
            (75, "HOT"),
            (74, "WARM"),
            (55, "WARM"),
            (54, "COLD"),
            (35, "COLD"),
            (34, "LOW"),
            (0, "LOW"),
        ],
    )
    def test_default_bands(self, score: int, expected: str) -> None:
        assert classify(score, intent=Intent.STAND) == expected

    def test_configurable_thresholds(self) -> None:
        assert classify(70, intent=Intent.STAND, hot_min=65) == "HOT"
        assert classify(50, intent=Intent.STAND, warm_min=45, cold_min=40) == "WARM"

    def test_visitor_override_wins_over_score(self) -> None:
        loud_visitor = LeadAnswers(
            intent=Intent.VISITOR,
            company_type=CompanyType.MANUFACTURER,
            category=Category.DAIRY_AND_CHEESE,
            website="a.uz",
            instagram="@a",
            contact_name="A",
            position="B",
            phone="+998901234567",
            preferred_stand_size=StandSize.SIZE_36_PLUS,
            readiness=Readiness.READY_TO_BOOK,
        )
        result = score_lead(loud_visitor)
        assert result.score > 75  # score is real...
        assert (
            classify(result.score, intent=loud_visitor.intent) == "VISITOR"
        )  # ...but the class is not

    def test_high_intent_override_forces_hot(self) -> None:
        assert classify(30, intent=Intent.STAND, high_intent=True) == "HOT"


class TestHighIntentOverride:
    def test_requires_all_three_conditions(self) -> None:
        assert is_high_intent(
            LeadAnswers(
                intent=Intent.STAND, readiness=Readiness.READY_TO_BOOK, phone="+998901234567"
            )
        )
        assert not is_high_intent(
            LeadAnswers(intent=Intent.STAND, readiness=Readiness.READY_TO_BOOK)
        )
        assert not is_high_intent(
            LeadAnswers(intent=Intent.PRICING, readiness=Readiness.READY_TO_BOOK, phone="+998")
        )
        assert not is_high_intent(
            LeadAnswers(intent=Intent.STAND, readiness=Readiness.MANAGER_CALL, phone="+998")
        )

    def test_override_qualifies_even_with_thin_profile(self) -> None:
        answers = LeadAnswers(
            intent=Intent.STAND,
            readiness=Readiness.READY_TO_BOOK,
            phone="+998901234567",
            company_name="Beach Bar",
        )
        result = score_lead(answers)
        assert result.score < 75  # only 30 + 10 + 20 = 60 -> WARM band
        assert result.high_intent is True
        assert classify(result.score, intent=answers.intent, high_intent=True) == "HOT"
        assert should_send_to_sales_group(answers, "HOT", high_intent=True) is True


class TestSalesGroupGate:
    def test_warm_with_phone_and_company_is_sent(self) -> None:
        answers = base(phone="+998901234567", company_name="X")
        assert should_send_to_sales_group(answers, "WARM") is True

    def test_warm_without_phone_is_not_sent(self) -> None:
        answers = base(phone=None)
        assert should_send_to_sales_group(answers, "WARM") is False

    def test_warm_without_company_name_is_not_sent(self) -> None:
        answers = base(company_name="  ")
        assert should_send_to_sales_group(answers, "WARM") is False

    def test_cold_is_not_sent_by_default(self) -> None:
        assert should_send_to_sales_group(base(), "COLD") is False

    def test_cold_can_be_enabled_by_configuration(self) -> None:
        assert should_send_to_sales_group(base(), "COLD", min_classification="cold") is True

    def test_hot_only_mode(self) -> None:
        assert should_send_to_sales_group(base(), "WARM", min_classification="hot") is False
        assert should_send_to_sales_group(base(), "HOT", min_classification="hot") is True

    def test_requirements_can_be_relaxed(self) -> None:
        assert (
            should_send_to_sales_group(
                base(phone=None, company_name=None),
                "WARM",
                require_phone=False,
                require_company_name=False,
            )
            is True
        )

    def test_visitors_are_never_sent(self) -> None:
        answers = LeadAnswers(intent=Intent.VISITOR, phone="+998901234567", company_name="X")
        assert should_send_to_sales_group(answers, "VISITOR", high_intent=True) is False
