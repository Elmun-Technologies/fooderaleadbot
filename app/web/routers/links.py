"""Ad tracking links page: create a named link, copy it, watch per-link stats."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
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
