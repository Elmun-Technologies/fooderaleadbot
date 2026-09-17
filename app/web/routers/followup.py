"""Follow-up marketing router."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.web.auth import get_lang, require_auth
from app.web.i18n import t as translate
from app.web.deps import get_repo, get_bot
from app.database.models import FollowUpTrigger

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()


@router.get("/followup", response_class=HTMLResponse)
async def followup_list(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    templates_list = await repo.list_followup_templates()
    logs = await repo.list_followup_logs(limit=50)
    total_logs = await repo.count_followup_logs()

    # Stats per trigger
    from collections import Counter

    trigger_counts = Counter([t.trigger for t in templates_list])

    return templates.TemplateResponse(
        request,
        "followup.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "templates": templates_list,
            "logs": logs,
            "total_logs": total_logs,
            "trigger_counts": trigger_counts,
            "triggers": [tr.value for tr in FollowUpTrigger],
        },
    )


@router.get("/followup/create", response_class=HTMLResponse)
async def followup_create_page(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
):
    return templates.TemplateResponse(
        request,
        "followup_create.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "triggers": [tr.value for tr in FollowUpTrigger],
        },
    )


@router.post("/followup/create")
async def followup_create(
    name: str = Form(...),
    trigger: str = Form(...),
    delay_hours: int = Form(...),
    language: str = Form(...),
    text: str = Form(...),
    filter_classification: str = Form(default=""),
    filter_lead_type: str = Form(default=""),
    is_active: str = Form(default=""),
    priority: int = Form(default=0),
    photo: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    user: str = Depends(require_auth),
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
            msg = await bot.send_photo(settings.sales_group_id, photo=input_file, caption="Followup photo - delete")
            if msg.photo:
                photo_file_id = msg.photo[-1].file_id
            try:
                await bot.delete_message(settings.sales_group_id, msg.message_id)
            except Exception:
                pass
        except Exception:
            pass

    if document and document.filename and bot and settings.sales_group_id:
        try:
            content = await document.read()
            from aiogram.types import BufferedInputFile

            input_file = BufferedInputFile(content, filename=document.filename)
            msg = await bot.send_document(settings.sales_group_id, document=input_file, caption="Followup doc - delete")
            if msg.document:
                document_file_id = msg.document.file_id
                document_name = document.filename
            try:
                await bot.delete_message(settings.sales_group_id, msg.message_id)
            except Exception:
                pass
        except Exception:
            pass

    await repo.create_followup_template(
        name=name,
        trigger=trigger,
        delay_hours=delay_hours,
        language=language,
        text=text,
        photo_file_id=photo_file_id,
        document_file_id=document_file_id,
        document_name=document_name,
        filter_classification=filter_classification or None,
        filter_lead_type=filter_lead_type or None,
        is_active=is_active == "on",
        priority=priority,
    )

    return RedirectResponse(url="/admin/followup", status_code=302)


@router.get("/followup/{template_id}", response_class=HTMLResponse)
async def followup_detail(
    template_id: int,
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    template = await repo.get_followup_template(template_id)
    if not template:
        return HTMLResponse(content="Not found", status_code=404)

    # Find targets preview
    targets = await repo.find_users_for_followup(template)

    return templates.TemplateResponse(
        request,
        "followup_detail.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "template": template,
            "targets": targets[:50],
            "total_targets": len(targets),
            "triggers": [tr.value for tr in FollowUpTrigger],
        },
    )


@router.post("/followup/{template_id}/toggle")
async def followup_toggle(
    template_id: int,
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    template = await repo.get_followup_template(template_id)
    if template:
        await repo.update_followup_template(template_id, is_active=not template.is_active)
    return RedirectResponse(url="/admin/followup", status_code=302)


@router.post("/followup/{template_id}/delete")
async def followup_delete(
    template_id: int,
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    await repo.delete_followup_template(template_id)
    return RedirectResponse(url="/admin/followup", status_code=302)


@router.post("/followup/{template_id}/edit")
async def followup_edit(
    template_id: int,
    name: str = Form(...),
    trigger: str = Form(...),
    delay_hours: int = Form(...),
    language: str = Form(...),
    text: str = Form(...),
    priority: int = Form(default=0),
    is_active: str = Form(default=""),
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
):
    await repo.update_followup_template(
        template_id,
        name=name,
        trigger=trigger,
        delay_hours=delay_hours,
        language=language,
        text=text,
        priority=priority,
        is_active=is_active == "on",
    )
    return RedirectResponse(url=f"/admin/followup/{template_id}", status_code=302)


@router.post("/followup/run")
async def followup_run_now(
    background_tasks: BackgroundTasks,
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
    bot=Depends(get_bot),
):
    from app.services.followup_service import FollowUpService

    async def _run():
        service = FollowUpService(bot, repo)
        await service.ensure_default_templates()
        scheduled = await service.schedule_due_followups()
        sent, failed = await service.send_due_followups(limit=200)
        print(f"Follow-up run: scheduled {scheduled}, sent {sent}, failed {failed}")

    background_tasks.add_task(_run)

    return RedirectResponse(url="/admin/followup", status_code=302)
