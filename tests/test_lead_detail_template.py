"""Admin lead page: legacy answers are shown only for the leads that have them.

The questionnaire was simplified (no website / Instagram / industry-relation questions), but
the records collected earlier must stay readable.  The lead card is covered by
``tests/test_notification.py``; this module covers the admin HTML page.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from app.database.models import Classification, Lead, LeadType
from app.i18n import t as translate
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "app" / "web" / "templates"
ENV = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _request() -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path="/admin/leads"), url_for=lambda *a, **k: "/")


def render_lead_detail(lead: Lead, lang: str = "uz") -> str:
    """Render the admin page exactly like the router does (one lead, no events/chat)."""
    template = ENV.get_template("lead_detail.html")
    return template.render(
        request=_request(),
        lang=lang,
        t=lambda key: translate(key, lang),
        user="admin",
        lead=lead,
        events=[],
        chat_history=[],
        statuses=["NEW", "CONTACTED"],
    )


def lead(**overrides: object) -> Lead:
    values: dict[str, object] = {
        "id": 1,
        "lead_code": "FD000001",
        "telegram_user_id": 42,
        "language": "uz",
        "lead_type": LeadType.EXHIBITOR.value,
        "lead_status": "NEW",
        "score": 96,
        "classification": Classification.HOT.value,
    }
    values.update(overrides)
    return Lead(**values)  # type: ignore[arg-type]


class TestSimplifiedLead:
    def test_intent_is_shown(self) -> None:
        html = render_lead_detail(lead(intent="stand"))
        assert "Maqsad:" in html
        assert "stand" in html

    def test_no_empty_legacy_rows(self) -> None:
        html = render_lead_detail(
            lead(intent="stand", company_name="ACME", website=None, instagram=None)
        )
        for label in ("Sayt:", "Instagram:", "Sanoat bilan aloqa:"):
            assert label not in html, f"{label} must not be rendered when there is no value"


class TestLegacyLead:
    def test_legacy_fields_are_rendered_when_present(self) -> None:
        html = render_lead_detail(
            lead(
                intent="pricing",
                region="foreign",
                country="Kazakhstan",
                website="legacy.uz",
                instagram="@legacy",
                business_relation="retail",
            )
        )
        assert "pricing" in html
        assert "Kazakhstan" in html
        assert "legacy.uz" in html
        assert "@legacy" in html
        assert "retail" in html
        for label in ("Sayt:", "Instagram:", "Sanoat bilan aloqa:", "Hudud:"):
            assert label in html

    def test_visitor_lead_has_no_commercial_rows(self) -> None:
        html = render_lead_detail(
            lead(
                lead_type=LeadType.VISITOR.value,
                intent="visitor",
                contact_name="Malika",
                region="samarkand",
                classification=Classification.VISITOR.value,
            )
        )
        assert "Malika" in html and "samarkand" in html
        assert "Sayt:" not in html and "Instagram:" not in html


@pytest.mark.parametrize("lang", ["uz", "ru"])
def test_page_renders_in_both_languages(lang: str) -> None:
    html = render_lead_detail(lead(intent="stand", company_name="ACME"), lang=lang)
    assert "ACME" in html
