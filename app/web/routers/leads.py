"""Leads router."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.web.auth import get_lang, require_auth
from app.web.i18n import t as translate
from app.web.deps import get_repo, get_bot
from app.database.models import LeadStatus

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()


@router.get("/leads", response_class=HTMLResponse)
async def leads_list(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
    q: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    settings: Settings = Depends(get_settings),
):
    limit = 25
    offset = (page - 1) * limit

    if q:
        leads = await repo.search_leads(q, limit=limit)
        total = len(leads)
    else:
        leads = await repo.list_leads(
            classification=classification,
            status=status,
            source=source,
            limit=limit,
            offset=offset,
            only_completed=False,
        )
        total = await repo.count_leads(
            classification=classification, status=status, source=source, only_completed=False
        )

    pages = max(1, (total + limit - 1) // limit)

    return templates.TemplateResponse(
        request,
        "leads.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "leads": leads,
            "total": total,
            "page": page,
            "pages": pages,
            "q": q or "",
            "classification": classification or "",
            "status": status or "",
            "source": source or "",
            "statuses": [s.value for s in LeadStatus],
        },
    )


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
async def lead_detail(
    request: Request,
    lead_id: int,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    lead = await repo.get_lead(lead_id)
    if not lead:
        return HTMLResponse(content="Lead not found", status_code=404)

    events = await repo.events_for_lead(lead.id)
    chat_history = await repo.list_chat_messages(lead_id=lead.id, limit=100)

    return templates.TemplateResponse(
        request,
        "lead_detail.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "lead": lead,
            "events": events,
            "chat_history": chat_history,
            "statuses": [s.value for s in LeadStatus],
        },
    )


@router.post("/leads/{lead_id}/status")
async def change_status(
    lead_id: int,
    status: str = Form(...),
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
    bot=Depends(get_bot),
    settings: Settings = Depends(get_settings),
):
    from app.services.lead_service import LeadService
    from app.services.notification import LeadNotifier

    notifier = LeadNotifier(bot, settings)
    service = LeadService(repo, settings, notifier)
    result = await service.change_status(
        lead_id, status, manager_user_id=None, manager_username=user, force=True
    )
    return RedirectResponse(url=f"/admin/leads/{lead_id}", status_code=302)


@router.post("/leads/{lead_id}/message")
async def send_message_to_lead(
    lead_id: int,
    message: str = Form(...),
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
    bot=Depends(get_bot),
):
    lead = await repo.get_lead(lead_id)
    if not lead:
        return HTMLResponse(content="Lead not found", status_code=404)

    from app.services.chat_service import ChatService

    chat_service = ChatService(bot, repo)
    await chat_service.send_to_user(
        lead.telegram_user_id,
        text=message,
        lead_id=lead.id,
        admin_username=user,
    )

    return RedirectResponse(url=f"/admin/leads/{lead_id}", status_code=302)


@router.get("/leads/export/csv")
async def export_csv(
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
    classification: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
):
    leads = await repo.export_leads(
        classification=classification, status=status, source=source, only_completed=False
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "lead_code",
            "company_name",
            "contact_name",
            "phone",
            "region",
            "country",
            "category",
            "company_type",
            "classification",
            "score",
            "is_high_intent",
            "status",
            "source",
            "campaign",
            "creative",
            "telegram_username",
            "telegram_user_id",
            "language",
            "website",
            "instagram",
            "stand_size",
            "readiness",
            "created_at",
            "completed_at",
        ]
    )
    for lead in leads:
        writer.writerow(
            [
                lead.lead_code,
                lead.company_name or "",
                lead.contact_name or "",
                lead.phone or "",
                lead.region or "",
                lead.country or "",
                lead.category or "",
                lead.company_type or "",
                lead.classification or "",
                lead.score or 0,
                lead.is_high_intent,
                lead.lead_status or "",
                lead.source or "",
                lead.campaign or "",
                lead.creative or "",
                lead.telegram_username or "",
                lead.telegram_user_id,
                lead.language or "",
                lead.website or "",
                lead.instagram or "",
                lead.preferred_stand_size or "",
                lead.readiness or "",
                lead.created_at.isoformat() if lead.created_at else "",
                lead.completed_at.isoformat() if lead.completed_at else "",
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=foodera_leads_{datetime.now().date()}.csv"},
    )


@router.get("/leads/export/excel")
async def export_excel(
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    try:
        import openpyxl

        leads = await repo.export_leads(only_completed=False)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Leads"
        ws.append(
            [
                "lead_code",
                "company_name",
                "contact_name",
                "phone",
                "region",
                "category",
                "classification",
                "score",
                "status",
                "source",
                "campaign",
                "telegram_username",
                "telegram_user_id",
                "created_at",
            ]
        )
        for lead in leads:
            ws.append(
                [
                    lead.lead_code,
                    lead.company_name,
                    lead.contact_name,
                    lead.phone,
                    lead.region,
                    lead.category,
                    lead.classification,
                    lead.score,
                    lead.lead_status,
                    lead.source,
                    lead.campaign,
                    lead.telegram_username,
                    lead.telegram_user_id,
                    lead.created_at.isoformat() if lead.created_at else "",
                ]
            )
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=foodera_leads_{datetime.now().date()}.xlsx"
            },
        )
    except ImportError:
        return await export_csv(user=user, repo=repo)
