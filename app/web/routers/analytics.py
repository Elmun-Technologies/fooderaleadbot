"""Analytics router."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.web.auth import get_lang, require_auth
from app.web.i18n import t as translate
from app.web.deps import get_repo

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
    settings: Settings = Depends(get_settings),
):
    from app.handlers.admin import start_of_today

    since = start_of_today(settings.display_timezone)

    today_counts = await repo.classification_counts(since=since)
    total_counts = await repo.classification_counts()
    statuses = await repo.status_counts()
    statuses_today = await repo.status_counts(since=since)
    sources = await repo.source_breakdown(limit=25)
    payloads = await repo.payload_breakdown(limit=25)
    funnel = await repo.funnel_counts()
    funnel_today = await repo.funnel_counts(since=since)
    avg_score = await repo.average_score()
    avg_today = await repo.average_score(since=since)
    total_completed = await repo.count_leads()
    today_total = await repo.count_leads(since=since)
    starts = await repo.started_count()
    starts_today = await repo.started_count(since=since)
    visitors = await repo.visitor_count()
    visitors_today = await repo.visitor_count(since=since)

    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "today_counts": today_counts,
            "total_counts": total_counts,
            "statuses": statuses,
            "statuses_today": statuses_today,
            "sources": sources,
            "payloads": payloads,
            "funnel": funnel,
            "funnel_today": funnel_today,
            "avg_score": avg_score,
            "avg_today": avg_today,
            "total_completed": total_completed,
            "today_total": today_total,
            "starts": starts,
            "starts_today": starts_today,
            "visitors": visitors,
            "visitors_today": visitors_today,
        },
    )
