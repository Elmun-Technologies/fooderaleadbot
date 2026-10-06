#!/usr/bin/env python3
"""Offline demo of the FOODERA lead bot - no token, no database, no Telegram.

    python scripts/demo_run.py                    # exhibitor lead, uz + ru
    python scripts/demo_run.py --lang ru
    python scripts/demo_run.py --intent visitor   # the visitor funnel instead

It renders the exact copy a lead sees, the score the deterministic model produces and
the card the sales group receives (including the footer a manager leaves behind).
Useful for reviewing wording and thresholds without wiring the bot to a chat.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `python scripts/demo_run.py` from anywhere
    sys.path.insert(0, str(ROOT))

from aiogram.types import InlineKeyboardMarkup  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database.models import Lead  # noqa: E402
from app.flow import STEPS, progress_of, steps_for  # noqa: E402
from app.handlers.engine import build_question  # noqa: E402
from app.i18n import t  # noqa: E402
from app.keyboards.inline import lead_actions_kb  # noqa: E402
from app.services import scoring  # noqa: E402
from app.services.notification import (  # noqa: E402
    build_lead_card,
    build_visitor_card,
    card_status_line,
)

#: The simplified exhibitor funnel: no online-presence / links question any more.
SAMPLE_EXHIBITOR: dict[str, Any] = {
    "intent": "stand",
    "company_type": "manufacturer",
    "category": "non_alcoholic_drinks",
    "company_name": "Chirchik Juice Plant",
    "region": "tashkent",
    "contact_name": "Dilshod Rahimov",
    "position": "Head of Sales",
    "phone": "+998901234567",
    "preferred_stand_size": "size_27",
    "readiness": "ready_to_book",
    "source": "telegram_ads",
    "campaign": "foodera",
    "creative": "uz_01",
}

#: The visitor funnel is four questions: intent, name, optional phone, region.
SAMPLE_VISITOR: dict[str, Any] = {
    "intent": "visitor",
    "contact_name": "Malika Yusupova",
    "phone": "+998935554411",
    "region": "samarkand",
    "source": "qr",
    "campaign": "samarkand_stand3",
}


def rule(title: str) -> None:
    print(f"\n\n── {title} " + "─" * max(4, 74 - len(title)))


def make_lead(
    values: dict[str, Any], *, code: str, score: int, classification: str, high: bool
) -> Lead:
    """An unbound ORM row: the builders only read attributes, so no session is needed."""
    lead = Lead(
        id=42,
        lead_code=code,
        telegram_user_id=4242,
        telegram_first_name="Demo",
        telegram_username="demo_user",
        language="uz",
        score=score,
        classification=classification,
        is_high_intent=high,
        is_draft=False,
        lead_status="NEW",
        created_at=datetime(2026, 9, 17, 9, 30, tzinfo=UTC),
        completed_at=datetime(2026, 9, 17, 9, 36, tzinfo=UTC),
    )
    for key, value in values.items():
        setattr(lead, key, value)
    return lead


def render_keyboard(markup: InlineKeyboardMarkup | None) -> str:
    if markup is None:
        return "📱 [ Share my phone number ]  (Telegram contact button)"
    rows = getattr(markup, "inline_keyboard", None) or getattr(markup, "keyboard", None) or []
    return "\n      ".join("   ".join(button.text or "" for button in row) for row in rows)


def show_funnel(lead: Lead, lang: str) -> None:
    answers = lead.field_values()
    print("One question per screen, in this order (✓ marks the answer already stored):\n")
    for index, key in enumerate(steps_for(answers), start=1):
        render = build_question(lead, key, lang)
        first_line = render.text.splitlines()[0]
        question = t(STEPS[key].question_key, lang)
        note = "  [optional — the user may Skip]" if STEPS[key].optional else ""
        print(f"  {index}. {first_line}  {question}{note}")
        print(f"      {render_keyboard(render.keyboard or render.reply_keyboard)}")
    number, total = progress_of("intent", answers)
    print(f"\n  progress pill while answering: “{t('progress', lang, step=number, total=total)}”")
    if str(lead.intent or "") == "visitor":
        print(
            "  (a visitor sees 1/4: intent, name, optional phone and region - the industry\n"
            "   question is gone, and the country question appears only after “outside\n"
            "   Uzbekistan”, so the counter never counts a question that will not be asked)"
        )
    else:
        print(
            "  (a brand new exhibitor sees 1/9: the first question offers two answers only -\n"
            "   stand or visitor - and the country question appears only after “outside\n"
            "   Uzbekistan”, so the counter never counts a question that will not be asked)"
        )


def show_score(lead: Lead, values: dict[str, Any], settings: Settings) -> None:
    answers = scoring.answers_from_lead(values)
    result = scoring.score_lead(answers)
    classification = scoring.classify(
        result.score,
        intent=str(values.get("intent") or ""),
        hot_min=settings.hot_min_score,
        warm_min=settings.warm_min_score,
        cold_min=settings.cold_min_score,
        high_intent=result.high_intent,
    )
    push = scoring.should_send_to_sales_group(
        answers,
        classification,
        high_intent=result.high_intent,
        min_classification=settings.qualify_min_classification,
        require_phone=settings.require_phone_for_sales,
        require_company_name=settings.require_company_name_for_sales,
    )
    print("Every point comes from a rule, never from a language model:\n")
    for name, points in sorted(result.breakdown, key=lambda item: -item[1]):
        print(f"  {name:<16} {points:>4}   {'█' * min(points, 30)}")
    print(f"\n  total {result.score}/100  →  {classification}")
    print(f"  forwarded to the sales group: {'yes' if push else 'no (kept in the database only)'}")
    print("  (the score is internal - the person filling the form never sees it)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--lang", choices=["uz", "ru", "both"], default="both")
    # ``pricing`` / ``partner`` are legacy answers: they exist in the database from
    # before the simplification, but new users can only choose stand or visitor.
    parser.add_argument("--intent", choices=["stand", "visitor"], default="stand")
    args = parser.parse_args()

    settings = Settings(
        _env_file=None,
        bot_token="demo:token",
        database_url="sqlite+aiosqlite:///:memory:",
        sales_group_id=-1001234567890,
        visitor_group_id=-1009876543210 if args.intent == "visitor" else None,
        admin_user_ids=[111],
        support_username="foodera_support",
        display_timezone="Asia/Tashkent",
    )

    is_visitor = args.intent == "visitor"
    values = SAMPLE_VISITOR if is_visitor else {**SAMPLE_EXHIBITOR, "intent": args.intent}
    preview_answers = scoring.answers_from_lead(values)
    preview = scoring.score_lead(preview_answers)
    classification = scoring.classify(
        preview.score,
        intent=str(values.get("intent") or ""),
        hot_min=settings.hot_min_score,
        warm_min=settings.warm_min_score,
        cold_min=settings.cold_min_score,
        high_intent=preview.high_intent,
    )
    lead = make_lead(
        values,
        code="FD000042",
        score=preview.score,
        classification=classification,
        high=preview.high_intent,
    )

    print("\033[1mFOODERA EXPO 2026 — lead qualification bot, offline preview\033[0m")
    print(f"funnel: {args.intent}")

    for lang in ["uz", "ru"] if args.lang == "both" else [args.lang]:
        rule(f"the funnel as the user sees it ({lang})")
        show_funnel(lead, lang)

        if is_visitor:
            rule(f"visitor card → VISITOR_GROUP_ID ({lang})")
            print(build_visitor_card(lead, lang=lang, settings=settings))
            print("\n  no score, no stand data - and never mixed into the exhibitor group")
            continue

        rule(f"scoring ({lang})")
        show_score(lead, values, settings)

        rule(f"lead card → SALES_GROUP_ID ({lang})")
        print(build_lead_card(lead, lang=lang, settings=settings))
        print(f"\n  {render_keyboard(lead_actions_kb(lead.id or 42, lang))}")

        lead.lead_status = "CONTACTED"
        lead.status_changed_at = datetime(2026, 9, 17, 9, 40, tzinfo=UTC)
        lead.manager_username = "sales_manager"
        rule(f"…the card footer after a manager taps “{t('btn.status.contacted', lang)}” ({lang})")
        print(f"  {card_status_line(lead, lang)}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
