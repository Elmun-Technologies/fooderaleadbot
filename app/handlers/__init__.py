"""Handlers package.

Router order matters: the visitor router must be consulted before the generic
qualification router (it intercepts the visitor branch of Q1), and the fallback router
must always be last.
"""

from __future__ import annotations

from aiogram import Router

from app.handlers import admin, fallback, group_chat, language, qualification, start, visitor

__all__ = ["on_error", "routers"]

from app.handlers.fallback import on_error


def routers() -> list[Router]:
    """Routers in registration order."""
    return [
        start.router,
        language.router,
        visitor.router,
        qualification.router,
        admin.router,
        group_chat.router,
        fallback.router,
    ]
