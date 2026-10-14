"""Ad tracking links page: create a named link, copy it, watch per-link stats.

The list page counts starts → applications → qualified; ``/admin/links/{id}``
opens the breakdown for one link and answers "who exactly came through it and how
far did they get".
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.database.models import Classification, LeadStatus
from app.database.repository import TRACKING_STAGES
from app.services.tracking_links import (
    SOURCE_CHOICES,
    build_deep_link,
    normalize_source,
    slugify,
    source_choice_label,
    unique_payload,
)
from app.web.auth import get_lang, require_auth
from app.web.deps import get_repo
from app.web.i18n import t as translate

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()

_QUALIFIED: tuple[str, ...] = (Classification.HOT.value, Classification.WARM.value)

#: ``?stage=`` values the detail page understands (None / junk = everyone)
_STAGE_FILTERS: tuple[str, ...] = (*TRACKING_STAGES, "qualified", "booked")


def _matches_stage(person: dict[str, Any], stage: str) -> bool:
    """Is this person part of the funnel slice the card stands for?"""
    lead = person["lead"]
    if stage == "qualified":
        return lead is not None and lead.classification in _QUALIFIED
    if stage == "booked":
        return lead is not None and lead.lead_status == LeadStatus.BOOKED.value
    return person["stage"] == stage


# The bot username is fetched once and cached (needed to build t.me links).
_bot_username: str | None = None


async def _get_bot_username(settings: Settings) -> str:
    global _bot_username
    if _bot_username:
        return _bot_username
    from app.web.app import get_bot_instance

    bot = get_bot_instance()
    try:
        if bot is not None:
            me = await bot.get_me()
            _bot_username = me.username or ""
        else:  # panel running without the bot process - one-off API call
            from aiogram import Bot

            temp = Bot(token=settings.bot_token)
            try:
                me = await temp.get_me()
                _bot_username = me.username or ""
            finally:
                await temp.session.close()
    except Exception:  # pragma: no cover - network issues must not kill the page
        logger.warning("could not fetch bot username for tracking links")
        return ""
    return _bot_username or ""


@router.get("/links", response_class=HTMLResponse)
async def links_page(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
    settings: Settings = Depends(get_settings),
    created: str | None = None,
    error: str | None = None,
):
    rows = await repo.tracking_link_stats()
    username = await _get_bot_username(settings)
    links = [
        {
            **row,
            "url": build_deep_link(username or "YOUR_BOT", row["payload"]),
            "source_label": source_choice_label(row["source"], lang),
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request,
        "links.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "links": links,
            "bot_username": username,
            "source_choices": [
                (key, ru if lang == "ru" else uz) for key, uz, ru in SOURCE_CHOICES
            ],
            "created_payload": created,
            "error": error,
        },
    )


@router.get("/links/{link_id}", response_class=HTMLResponse)
async def link_detail(
    request: Request,
    link_id: int,
    # the dependencies of this route use ``Annotated``: the ``Depends(...)`` calls
    # in default values trigger ruff B008 on every route that uses them
    user: Annotated[str, Depends(require_auth)],
    lang: Annotated[str, Depends(get_lang)],
    repo: Annotated[Any, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    stage: str | None = Query(default=None),
):
    """One link in detail: the funnel and the actual people behind every number."""
    link = await repo.get_tracking_link(link_id)
    if link is None:
        return RedirectResponse(url="/admin/links", status_code=302)

    people = await repo.tracking_link_people(link.payload)
    counts: dict[str, int] = {
        "total": len(people),
        **{
            key: sum(1 for person in people if _matches_stage(person, key))
            for key in _STAGE_FILTERS
        },
    }

    active_stage = stage if stage in _STAGE_FILTERS else None
    if active_stage:
        people = [person for person in people if _matches_stage(person, active_stage)]

    username = await _get_bot_username(settings)
    return templates.TemplateResponse(
        request,
        "link_detail.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "link": link,
            "url": build_deep_link(username or "YOUR_BOT", link.payload),
            "source_label": source_choice_label(link.source, lang),
            "people": people,
            "counts": counts,
            "active_stage": active_stage,
        },
    )


@router.post("/links/create")
async def create_link(
    request: Request,
    title: str = Form(...),
    source: str = Form("other"),
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    title = title.strip()
    if not title:
        return RedirectResponse(url="/admin/links?error=empty", status_code=302)

    base = slugify(title)
    if not base:
        return RedirectResponse(url="/admin/links?error=badname", status_code=302)

    taken = await repo.tracking_payloads()
    payload = unique_payload(base, taken)
    link = await repo.create_tracking_link(
        title=title, payload=payload, source=normalize_source(source)
    )
    return RedirectResponse(url=f"/admin/links?created={link.payload}", status_code=302)


@router.post("/links/{link_id}/delete")
async def delete_link(
    link_id: int,
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    await repo.delete_tracking_link(link_id)
    return RedirectResponse(url="/admin/links", status_code=302)
