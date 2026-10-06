#!/usr/bin/env python3
"""Pre-deploy sanity check: does *this* source tree contain the simplified questionnaire?

    python scripts/check_questionnaire.py            # exits 0 when everything is in place
    python scripts/check_questionnaire.py --quiet    # only failures

`fly deploy` ships whatever is in the working tree, so a checkout that is behind (or a
merge that dropped the change) silently re-deploys the old questionnaire - exactly what
happened with the Mac deploy of ``main``.  This script fails loudly instead: it loads the
real flow, keyboards, scoring model and catalogs and asserts the 2026 funnel.

Run it right before the deploy:

    python scripts/check_questionnaire.py && fly deploy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `python scripts/check_questionnaire.py` from anywhere
    sys.path.insert(0, str(ROOT))

from app.database.models import Lead  # noqa: E402
from app.flow import EXHIBITOR_PATH, STEPS, VISITOR_PATH  # noqa: E402
from app.handlers.engine import build_question  # noqa: E402
from app.i18n import t  # noqa: E402
from app.options import LEGACY_INTENTS, NEW_USER_INTENTS, Intent  # noqa: E402
from app.services.scoring import LeadAnswers, score_lead  # noqa: E402

REMOVED_STEPS = ("online", "url", "visitor_relation")
REMOVED_KEYS = ("q.online", "q.url", "q.v_relation", "err.url_format")
EXPECTED_EXHIBITOR = (
    "intent",
    "company_type",
    "category",
    "company_name",
    "region",
    "contact",
    "phone",
    "stand",
    "readiness",
)
EXPECTED_VISITOR = ("intent", "visitor_name", "visitor_phone", "visitor_region")

_failures: list[str] = []


def check(condition: bool, description: str) -> None:
    if not condition:
        _failures.append(description)


def _intent_callbacks() -> list[str]:
    render = build_question(Lead(lead_code="FD000000", telegram_user_id=1), "intent", "uz")
    rows = getattr(render.keyboard, "inline_keyboard", []) or []
    return [button.callback_data or "" for row in rows for button in row]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--quiet", action="store_true", help="print only failures")
    args = parser.parse_args()

    def ok(message: str) -> None:
        if not args.quiet:
            print(f"✅ {message}")

    # 1. the two funnels -----------------------------------------------------
    check(tuple(EXHIBITOR_PATH) == EXPECTED_EXHIBITOR, f"exhibitor path is {EXHIBITOR_PATH}")
    check(tuple(VISITOR_PATH) == EXPECTED_VISITOR, f"visitor path is {VISITOR_PATH}")
    for removed in REMOVED_STEPS:
        check(removed not in STEPS, f"step '{removed}' is still in STEPS")
    ok(f"exhibitor funnel: {' → '.join(EXHIBITOR_PATH)}")
    ok(f"visitor funnel:   {' → '.join(VISITOR_PATH)}")

    # 2. the first question offers exactly two answers -----------------------
    check(tuple(NEW_USER_INTENTS) == (Intent.STAND, Intent.VISITOR), "NEW_USER_INTENTS changed")
    callbacks = _intent_callbacks()
    check(callbacks == ["q:intent:stand", "q:intent:visitor"], f"intent buttons are {callbacks}")
    check(
        set(LEGACY_INTENTS) == {Intent.PRICING, Intent.PARTNER},
        f"legacy intents are {sorted(LEGACY_INTENTS)}",
    )
    ok(f"first question offers exactly: {', '.join(callbacks)}")

    # 3. legacy answers still validate but never score -----------------------
    for legacy in sorted(LEGACY_INTENTS):
        check(legacy not in NEW_USER_INTENTS, f"legacy intent {legacy} is advertised")
    legacy_answers = LeadAnswers.from_mapping(
        {"intent": "stand", "website": "old.uz", "instagram": "@old"}
    )
    legacy_score = score_lead(legacy_answers)
    check(
        "verification" not in legacy_score.breakdown_dict(),
        "website / Instagram still contribute to the score",
    )
    ok("legacy website / Instagram answers do not score (links block removed)")

    # 4. both catalogs are updated and still aligned -------------------------
    dates = {lang: t("event.dates", lang) for lang in ("uz", "ru")}
    for lang, value in dates.items():
        check("27–29" in value and "2026" in value, f"event dates for {lang} are '{value}'")
    keys_uz = set(__import__("app.i18n.catalog_uz", fromlist=["CATALOG"]).CATALOG)
    keys_ru = set(__import__("app.i18n.catalog_ru", fromlist=["CATALOG"]).CATALOG)
    check(keys_uz == keys_ru, "uz / ru catalogs have drifted apart")
    for key in REMOVED_KEYS:
        check(key not in keys_uz, f"catalog key '{key}' of a removed question is still there")
    ok(f"uz / ru catalogs aligned; FOODERA EXPO {dates['uz']}")

    if _failures:
        print("\n❌ this source tree does NOT contain the simplified questionnaire:")
        for failure in _failures:
            print(f"   · {failure}")
        print("\nDo not deploy it. Fetch the branch/PR with the questionnaire changes first.")
        return 1

    print("\n✅ this source tree is ready to deploy (simplified questionnaire present).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
