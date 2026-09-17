"""Simple session-based auth for admin panel."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_credentials(username: str, password: str, settings: Settings) -> bool:
    expected_user = settings.admin_panel_username or "admin"
    expected_pass = settings.admin_panel_password or ""
    # If no password set, allow any? No, require password if set, otherwise allow admin/admin
    if not expected_pass:
        # default password is admin if not set
        expected_pass = "admin"
    # constant time compare
    user_match = hmac.compare_digest(username, expected_user)
    pass_match = hmac.compare_digest(_hash_password(password), _hash_password(expected_pass))
    return user_match and pass_match


def create_session_token(username: str, settings: Settings) -> str:
    secret = settings.admin_panel_secret_key or "foodera-secret-key-change-me"
    timestamp = str(int(time.time()))
    random_part = secrets.token_hex(16)
    data = f"{username}:{timestamp}:{random_part}"
    signature = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    token = f"{data}:{signature}"
    return token


def verify_session_token(token: str, settings: Settings) -> Optional[str]:
    try:
        secret = settings.admin_panel_secret_key or "foodera-secret-key-change-me"
        parts = token.split(":")
        if len(parts) != 4:
            return None
        username, timestamp, random_part, signature = parts
        data = f"{username}:{timestamp}:{random_part}"
        expected_sig = hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        # Check expiry
        ttl_hours = settings.admin_panel_session_ttl_hours or 24
        if int(time.time()) - int(timestamp) > ttl_hours * 3600:
            return None
        return username
    except Exception:
        return None


async def get_current_user(
    request: Request,
    session: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
):
    if not session:
        return None
    return verify_session_token(session, settings)


async def require_auth(
    request: Request,
    session: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
):
    user = verify_session_token(session, settings) if session else None
    if not user:
        # Redirect to login
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return user


def get_lang(request: Request) -> str:
    lang = request.cookies.get("lang") or request.query_params.get("lang") or "uz"
    if lang not in ("uz", "ru"):
        lang = "uz"
    return lang
