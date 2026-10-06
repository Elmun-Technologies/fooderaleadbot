"""Follow-up template defaults and event-date maintenance."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.followup_service import FollowUpService


class _FakeRepository:
    def __init__(self, templates: list[SimpleNamespace]) -> None:
        self.templates = templates
        self.updated: list[int] = []

    async def list_followup_templates(self) -> list[SimpleNamespace]:
        return self.templates

    async def update_followup_template(self, template_id: int, **values: Any) -> SimpleNamespace:
        template = next(template for template in self.templates if template.id == template_id)
        for key, value in values.items():
            setattr(template, key, value)
        self.updated.append(template_id)
        return template


async def test_existing_templates_are_updated_to_the_new_event_dates() -> None:
    templates = [
        SimpleNamespace(id=1, text="📅 20–22 oktabr 2026"),
        SimpleNamespace(id=2, text="📅 20–22 октября 2026"),
        SimpleNamespace(id=3, text="No event date here"),
    ]
    repo = _FakeRepository(templates)

    await FollowUpService(bot=None, repo=repo).ensure_default_templates()

    assert templates[0].text == "📅 27–29 oktabr 2026"
    assert templates[1].text == "📅 27–29 октября 2026"
    assert templates[2].text == "No event date here"
    assert repo.updated == [1, 2]
