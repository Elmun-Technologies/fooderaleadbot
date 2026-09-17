"""Chat router - direct chat with leads."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.web.auth import get_lang, require_auth
from app.web.i18n import t as translate
from app.web.deps import get_repo, get_bot

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

router = APIRouter()


@router.get("/chat", response_class=HTMLResponse)
async def chat_list(
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    recent = await repo.list_recent_chats(limit=50)
    unread = await repo.unread_chat_count()

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "chats": recent,
            "unread": unread,
        },
    )


@router.get("/chat/{telegram_user_id}", response_class=HTMLResponse)
async def chat_detail(
    telegram_user_id: int,
    request: Request,
    user: str = Depends(require_auth),
    lang: str = Depends(get_lang),
    repo=Depends(get_repo),
):
    lead = await repo.last_completed(telegram_user_id)
    if not lead:
        leads = await repo.search_leads(str(telegram_user_id), limit=1)
        lead = leads[0] if leads else None

    history = await repo.get_chat_history(telegram_user_id, limit=200)

    await repo.mark_chat_read(telegram_user_id)

    return templates.TemplateResponse(
        request,
        "chat_detail.html",
        {
            "lang": lang,
            "t": lambda k: translate(k, lang),
            "user": user,
            "telegram_user_id": telegram_user_id,
            "lead": lead,
            "history": history,
        },
    )


@router.post("/chat/{telegram_user_id}/send")
async def chat_send(
    telegram_user_id: int,
    message: str = Form(...),
    user: str = Depends(require_auth),
    repo=Depends(get_repo),
    bot=Depends(get_bot),
    photo: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    settings: Settings = Depends(get_settings),
):
    lead = await repo.last_completed(telegram_user_id)
    lead_id = lead.id if lead else None

    photo_file_id = None
    document_file_id = None
    document_name = None

    if photo and photo.filename and bot and settings.sales_group_id:
        try:
            content = await photo.read()
            from aiogram.types import BufferedInputFile

            input_file = BufferedInputFile(content, filename=photo.filename)
            msg = await bot.send_photo(settings.sales_group_id, photo=input_file, caption="Chat photo - deleting")
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
            msg = await bot.send_document(settings.sales_group_id, document=input_file, caption="Chat doc - deleting")
            if msg.document:
                document_file_id = msg.document.file_id
                document_name = document.filename
            try:
                await bot.delete_message(settings.sales_group_id, msg.message_id)
            except Exception:
                pass
        except Exception:
            pass

    from app.services.chat_service import ChatService

    chat_service = ChatService(bot, repo)
    await chat_service.send_to_user(
        telegram_user_id,
        text=message,
        lead_id=lead_id,
        admin_username=user,
        photo_file_id=photo_file_id,
        document_file_id=document_file_id,
        file_name=document_name,
    )

    return RedirectResponse(url=f"/admin/chat/{telegram_user_id}", status_code=302)
