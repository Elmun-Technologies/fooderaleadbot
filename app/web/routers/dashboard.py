"""Dashboard router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import Settings, get_settings
from app.web.auth import get_lang, require_auth
from app.web.i18n import t as translate
from app.web.deps import get_repo

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
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
    today_total = await repo.count_leads(since=since)
    total_completed = await repo.count_leads()
    qualified = await repo.count_leads(classification=["HOT", "WARM"])
    statuses = await repo.status_counts()
    visitors = await repo.visitor_count()
    visitors_today = await repo.visitor_count(since=since)
    starts = await repo.started_count()
    funnel = await repo.funnel_counts()
    avg_score = await repo.average_score()
    sources = await repo.source_breakdown(limit=10)
    unread = await repo.unread_chat_count()
    recent_chats = await repo.list_recent_chats(limit=10)
    recent_leads = await repo.list_leads(limit=10)

    completion = round(100.0 * total_completed / starts, 1) if starts else 0.0

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "today_counts": today_counts,
            "total_counts": total_counts,
            "today_total": today_total,
            "total_completed": total_completed,
            "qualified": qualified,
            "statuses": statuses,
            "visitors": visitors,
            "visitors_today": visitors_today,
            "starts": starts,
            "funnel": funnel,
            "avg_score": avg_score,
            "sources": sources,
            "unread": unread,
            "recent_chats": recent_chats,
            "recent_leads": recent_leads,
            "completion": completion,
        },
    )
