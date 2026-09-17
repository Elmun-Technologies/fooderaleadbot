"""FastAPI admin panel application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Depends, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.web.auth import (
    create_session_token,
    get_current_user,
    get_lang,
    require_auth,
    verify_credentials,
    verify_session_token,
)
from app.web.i18n import t as translate

# Global bot instance (set from main.py)
_bot_instance: Any = None


def set_bot_instance(bot: Any) -> None:
    global _bot_instance
    _bot_instance = bot


def get_bot_instance() -> Any:
    return _bot_instance


BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="FOODERA Admin Panel", docs_url="/admin/api/docs", openapi_url="/admin/api/openapi.json")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = translate

# Static files
if STATIC_DIR.exists():
    app.mount("/admin/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/admin", include_in_schema=False)
async def admin_root(
    request: Request,
    session: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
):
    user = verify_session_token(session, settings) if session else None
    if not user:
        return RedirectResponse(url="/admin/login", status_code=302)
    return RedirectResponse(url="/admin/dashboard", status_code=302)


@app.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    lang: str = Depends(get_lang),
    error: str | None = None,
):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"lang": lang, "t": lambda k: translate(k, lang), "error": error},
    )


@app.post("/admin/login", include_in_schema=False)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
    lang: str = Depends(get_lang),
):
    if verify_credentials(username, password, settings):
        token = create_session_token(username, settings)
        response = RedirectResponse(url="/admin/dashboard", status_code=302)
        response.set_cookie(
            key="session", value=token, httponly=True, max_age=settings.admin_panel_session_ttl_hours * 3600, samesite="lax"
        )
        return response
    else:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "lang": lang,
                "t": lambda k: translate(k, lang),
                "error": translate("login_failed", lang),
            },
            status_code=401,
        )


@app.get("/admin/logout", include_in_schema=False)
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("session")
    return response


@app.get("/admin/lang/{lang_code}", include_in_schema=False)
async def switch_lang(lang_code: str, request: Request):
    if lang_code not in ("uz", "ru"):
        lang_code = "uz"
    referer = request.headers.get("referer", "/admin/dashboard")
    response = RedirectResponse(url=referer, status_code=302)
    response.set_cookie(key="lang", value=lang_code, max_age=30 * 24 * 3600)
    return response


# Include routers
from app.web.routers import dashboard, leads, broadcast, chat, analytics, followup

app.include_router(dashboard.router, prefix="/admin", tags=["dashboard"])
app.include_router(leads.router, prefix="/admin", tags=["leads"])
app.include_router(broadcast.router, prefix="/admin", tags=["broadcast"])
app.include_router(chat.router, prefix="/admin", tags=["chat"])
app.include_router(analytics.router, prefix="/admin", tags=["analytics"])
app.include_router(followup.router, prefix="/admin", tags=["followup"])


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


def create_app() -> FastAPI:
    return app
