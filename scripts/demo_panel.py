"""Run the admin panel locally with demo data (login: admin / admin).

Usage:  python scripts/demo_panel.py
Purely for local preview - uses a throwaway SQLite database.
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:DEMO-token-not-real")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{ROOT / 'demo_panel.db'}")
os.environ.setdefault("SALES_GROUP_ID", "-1001234567890")
os.environ.setdefault("ADMIN_USER_IDS", "111")
os.environ.setdefault("ADMIN_PANEL_PASSWORD", "admin")

import uvicorn

import app.web.deps as web_deps
import app.web.routers.links as links_router
from app.config import get_settings
from app.database.models import Classification
from app.database.repository import LeadRepository
from app.database.session import create_database
from app.web.app import app

settings = get_settings()
db = create_database(settings.database_url, echo=False)
web_deps._db = db
links_router._bot_username = "foodera_bot"  # offline demo - skip the Telegram call


async def seed() -> None:
    await db.create_schema()
    async with db.session() as session:
        repo = LeadRepository(session)
        if await repo.tracking_payloads():
            return  # already seeded

        demo_links = [
            ("Instagram dekabr aksiyasi", "instagram_dekabr_aksiyasi", "instagram", 34, 12, 5),
            ("Telegram Ads yangi yil", "telegram_ads_yangi_yil", "telegram_ads", 58, 21, 9),
            ("QR banner Expo kirish", "qr_banner_expo_kirish", "qr", 11, 4, 1),
        ]
        uid = 1000
        for title, payload, source, starts, leads, qualified in demo_links:
            await repo.create_tracking_link(title=title, payload=payload, source=source)
            for i in range(starts):
                uid += 1
                await repo.get_or_create_user(
                    telegram_user_id=uid,
                    defaults={"start_payload": payload, "source": source},
                )
                if i < leads:
                    lead = await repo.create_lead(
                        lead_code_prefix="FD",
                        telegram_user_id=uid,
                        language="uz",
                        start_payload=payload,
                        source=source,
                        campaign=payload,
                        company_name=f"Demo Food {uid}",
                        classification=(
                            Classification.HOT.value
                            if i < qualified
                            else Classification.COLD.value
                        ),
                        score=80 if i < qualified else 20,
                    )
                    await repo.update_lead(
                        lead.id, completed_at=datetime.now(UTC), is_draft=False
                    )


if __name__ == "__main__":
    asyncio.run(seed())
    print("Demo panel: http://0.0.0.0:8080/admin  (login: admin / admin)")
    uvicorn.run(app, host="0.0.0.0", port=8080)
