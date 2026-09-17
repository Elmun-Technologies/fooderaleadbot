"""Canonical answer values (single source of truth).

Every answer is stored in the database as one of these ASCII slugs, so scoring,
analytics and admin queries never depend on the display language.  Labels and
translations live in :mod:`app.i18n`; emojis live here because they are part of the
keyboard design, not the message text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "EXHIBITOR_INTENTS",
    "LEAD_INTENTS",
    "OPTION_GROUPS",
    "OTHER_VALUES",
    "Category",
    "CompanyType",
    "Intent",
    "OnlinePresence",
    "Option",
    "Readiness",
    "Region",
    "StandSize",
    "VisitorRelation",
]


class Intent(StrEnum):
    STAND = "stand"
    PRICING = "pricing"
    PARTNER = "partner"
    VISITOR = "visitor"


class CompanyType(StrEnum):
    MANUFACTURER = "manufacturer"
    DISTRIBUTOR = "distributor"
    IMPORTER = "importer"
    RETAIL = "retail"
    HORECA = "horeca"
    INGREDIENT = "ingredient"
    EQUIPMENT = "equipment"
    LOGISTICS = "logistics"
    OTHER = "other"


class Category(StrEnum):
    NON_ALCOHOLIC_DRINKS = "non_alcoholic_drinks"
    GROCERY = "grocery"
    FROZEN_AND_SEMI_FINISHED = "frozen_and_semi_finished"
    CONFECTIONERY_AND_BAKERY = "confectionery_and_bakery"
    CANNED_FOOD = "canned_food"
    OILS_AND_SAUCES = "oils_and_sauces"
    DAIRY_AND_CHEESE = "dairy_and_cheese"
    MEAT_POULTRY_EGGS = "meat_poultry_eggs"
    ORGANIC_AND_HEALTHY = "organic_and_healthy"
    FISH_AND_SEAFOOD = "fish_and_seafood"
    TEA_AND_COFFEE = "tea_and_coffee"
    INGREDIENTS_AND_COMPONENTS = "ingredients_and_components"
    PRODUCE_AND_DRIED_FRUITS = "produce_and_dried_fruits"
    EQUIPMENT_AND_TECHNOLOGIES = "equipment_and_technologies"
    LOGISTICS = "logistics"
    OTHER = "other"


class OnlinePresence(StrEnum):
    INSTAGRAM = "instagram"
    WEBSITE = "website"
    BOTH = "both"
    NONE = "none"


class StandSize(StrEnum):
    SIZE_9 = "size_9"
    SIZE_18 = "size_18"
    SIZE_27 = "size_27"
    SIZE_36_PLUS = "size_36_plus"
    UNDECIDED = "undecided"


class Readiness(StrEnum):
    READY_TO_BOOK = "ready_to_book"
    REVIEW_OPTIONS = "review_options"
    MANAGER_CALL = "manager_call"
    JUST_INTERESTING = "just_interesting"


class Region(StrEnum):
    TASHKENT = "tashkent"
    SAMARKAND = "samarkand"
    ANDIJAN = "andijan"
    FERGANA = "fergana"
    NAMANGAN = "namangan"
    BUKHARA = "bukhara"
    QASHQADARYO = "qashqadaryo"
    SURKHANDARYO = "surkhandaryo"
    KHOREZM = "khorezm"
    JIZZAKH = "jizzakh"
    SYRDARYA = "syrdarya"
    NAVOIY = "navoiy"
    KARAKALPAKSTAN = "karakalpakstan"
    OTHER_REGION = "other_region"
    FOREIGN = "foreign"


class VisitorRelation(StrEnum):
    PROFESSIONAL = "professional"
    RETAIL = "retail"
    HORECA = "horeca"
    DISTRIBUTOR = "distributor"
    STUDENT = "student"
    OTHER = "other"


#: intents that belong to the exhibitor sales funnel
EXHIBITOR_INTENTS: frozenset[str] = frozenset({Intent.STAND, Intent.PRICING})
#: intents handled by the sales team (exhibitors + partnership enquiries)
LEAD_INTENTS: frozenset[str] = EXHIBITOR_INTENTS | {Intent.PARTNER}
#: values that mean "not really a match" for scoring purposes
OTHER_VALUES: frozenset[str] = frozenset({"other", "other_region"})


@dataclass(frozen=True)
class Option:
    """One keyboard choice: a stored value plus its decorative emoji."""

    value: str
    emoji: str = ""

    @property
    def label_key(self) -> str:
        return self.value


def _group(enum_cls: type[StrEnum], emojis: dict[StrEnum, str] | None = None) -> tuple[Option, ...]:
    emojis = emojis or {}
    return tuple(Option(member.value, emojis.get(member, "")) for member in enum_cls)


#: group name -> ordered options.  ``app.i18n.option_label(group, value, lang)`` renders labels.
OPTION_GROUPS: dict[str, tuple[Option, ...]] = {
    "intent": _group(
        Intent,
        {
            Intent.STAND: "🏢",
            Intent.PRICING: "📋",
            Intent.PARTNER: "🤝",
            Intent.VISITOR: "👤",
        },
    ),
    "company_type": _group(
        CompanyType,
        {
            CompanyType.MANUFACTURER: "🏭",
            CompanyType.DISTRIBUTOR: "📦",
            CompanyType.IMPORTER: "🌍",
            CompanyType.RETAIL: "🛒",
            CompanyType.HORECA: "🍽",
            CompanyType.INGREDIENT: "🧪",
            CompanyType.EQUIPMENT: "⚙️",
            CompanyType.LOGISTICS: "🚚",
            CompanyType.OTHER: "📌",
        },
    ),
    "category": _group(Category),
    "region": _group(Region),
    "online": _group(
        OnlinePresence,
        {OnlinePresence.INSTAGRAM: "📷", OnlinePresence.WEBSITE: "🌐", OnlinePresence.BOTH: "✨"},
    ),
    "stand": _group(StandSize),
    "readiness": _group(
        Readiness,
        {
            Readiness.READY_TO_BOOK: "🔥",
            Readiness.REVIEW_OPTIONS: "✅",
            Readiness.MANAGER_CALL: "💬",
            Readiness.JUST_INTERESTING: "🔎",
        },
    ),
    "relation": _group(VisitorRelation),
}


def values_of(group: str) -> frozenset[str]:
    return frozenset(option.value for option in OPTION_GROUPS[group])
