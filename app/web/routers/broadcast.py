"""Broadcast router - rassilka with photo/file support."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.web.auth import get_lang, require_auth
from app.web.i18n import t as translate
from app.web.deps import get_repo, get_bot
from app.database.models import BroadcastStatus

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()


@router.get("/broadcast", response_class=HTMLResponse)
async def broadcast_list(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    broadcasts = await repo.list_broadcasts(limit=50)
    return templates.TemplateResponse(
        request,
        "broadcast.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "broadcasts": broadcasts,
        },
    )


@router.get("/broadcast/create", response_class=HTMLResponse)
async def broadcast_create_page(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    sources = await repo.source_breakdown(limit=20)
    return templates.TemplateResponse(
        request,
        "broadcast_create.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "sources": sources,
        },
    )


@router.post("/broadcast/create")
async def broadcast_create(
    request: Request,
    background_tasks: BackgroundTasks,
    text: str = Form(...),
    filter_classification: str = Form(default=""),
    filter_status: str = Form(default=""),
    filter_source: str = Form(default=""),
    filter_lead_type: str = Form(default=""),
    filter_language: str = Form(default=""),
    photo: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
    bot=Depends(get_bot),
    settings: Settings = Depends(get_settings),
):
    photo_file_id = None
    document_file_id = None
    document_name = None

    if photo and photo.filename and bot and settings.sales_group_id:
        try:
            content = await photo.read()
            from aiogram.types import BufferedInputFile

            input_file = BufferedInputFile(content, filename=photo.filename)
            msg = await bot.send_photo(settings.sales_group_id, photo=input_file, caption="Broadcast photo upload - will be deleted")
            if msg.photo:
                photo_file_id = msg.photo[-1].file_id
            try:
                await bot.delete_message(settings.sales_group_id, msg.message_id)
            except Exception:
                pass
        except Exception as e:
            print(f"Photo upload failed: {e}")
            photo_file_id = None

    if document and document.filename and bot and settings.sales_group_id:
        try:
            content = await document.read()
            from aiogram.types import BufferedInputFile

            input_file = BufferedInputFile(content, filename=document.filename)
            msg = await bot.send_document(settings.sales_group_id, document=input_file, caption="Broadcast doc upload - will be deleted")
            if msg.document:
                document_file_id = msg.document.file_id
                document_name = document.filename
            try:
                await bot.delete_message(settings.sales_group_id, msg.message_id)
            except Exception:
                pass
        except Exception as e:
            print(f"Doc upload failed: {e}")

    broadcast = await repo.create_broadcast(
        text=text,
        photo_file_id=photo_file_id,
        document_file_id=document_file_id,
        document_name=document_name,
        filter_classification=filter_classification or None,
        filter_status=filter_status or None,
        filter_source=filter_source or None,
        filter_lead_type=filter_lead_type or None,
        filter_language=filter_language or None,
        status=BroadcastStatus.DRAFT.value,
        created_by_username=user,
    )

    form_data = await request.form()
    send_now = form_data.get("send_now") == "on"
    if send_now:
        background_tasks.add_task(send_broadcast_task, broadcast.id, repo, bot)

    return RedirectResponse(url="/admin/broadcast", status_code=302)


async def send_broadcast_task(broadcast_id: int, repo, bot):
    from app.services.broadcast_service import BroadcastService

    service = BroadcastService(bot, repo)
    await service.send_broadcast(broadcast_id)


@router.get("/broadcast/{broadcast_id}", response_class=HTMLResponse)
async def broadcast_detail(
    broadcast_id: int,
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        return HTMLResponse(content="Broadcast not found", status_code=404)

    leads = await repo.leads_for_broadcast(broadcast)

    return templates.TemplateResponse(
        request,
        "broadcast_detail.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "broadcast": broadcast,
            "leads": leads[:100],
            "total_targets": len(leads),
        },
    )


@router.post("/broadcast/{broadcast_id}/send")
async def broadcast_send(
    broadcast_id: int,
    background_tasks: BackgroundTasks,
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
    bot=Depends(get_bot),
):
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        return HTMLResponse(content="Broadcast not found", status_code=404)

    background_tasks.add_task(send_broadcast_task, broadcast_id, repo, bot)

    return RedirectResponse(url=f"/admin/broadcast/{broadcast_id}", status_code=302)


@router.post("/broadcast/{broadcast_id}/delete")
async def broadcast_delete(
    broadcast_id: int,
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    from sqlalchemy import delete
    from app.database.models import Broadcast

    async with repo.session.begin():
        await repo.session.execute(delete(Broadcast).where(Broadcast.id == broadcast_id))
        await repo.session.commit()

    return RedirectResponse(url="/admin/broadcast", status_code=302)
