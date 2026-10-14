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
from app.database.models import Classification, LeadStatus
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
        names = ["Aziz", "Dilnoza", "Bekzod", "Nodira", "Sardor", "Kamola", "Jasur", "Malika"]
        uid = 1000
        for title, payload, source, starts, leads, qualified in demo_links:
            await repo.create_tracking_link(title=title, payload=payload, source=source)
            for i in range(starts):
                uid += 1
                name = names[i % len(names)]
                username = f"{name.lower()}_{uid}"
                await repo.get_or_create_user(
                    telegram_user_id=uid,
                    username=username,
                    first_name=name,
                    defaults={"start_payload": payload, "source": source},
                )
                lead_fields = {
                    "lead_code_prefix": "FD",
                    "telegram_user_id": uid,
                    "telegram_username": username,
                    "telegram_first_name": name,
                    "language": "uz",
                    "start_payload": payload,
                    "source": source,
                    "campaign": payload,
                    "company_name": f"Demo Food {uid}",
                }
                if i < leads:
                    lead = await repo.create_lead(
                        contact_name=f"{name} Demo",
                        phone=f"+99890{uid % 10_000_000:07d}",
                        classification=Classification.HOT.value
                        if i < qualified
                        else Classification.COLD.value,
                        score=80 if i < qualified else 20,
                        **lead_fields,
                    )
                    await repo.update_lead(lead.id, completed_at=datetime.now(UTC), is_draft=False)
                    if i % 4 == 3:  # part of the finished ones is already BOOKED
                        await repo.update_lead(lead.id, lead_status=LeadStatus.BOOKED.value)
                elif i < leads + 3:
                    # a few people stopped half way: "Anketa chala" on the detail page
                    await repo.create_lead(current_step="company", **lead_fields)


if __name__ == "__main__":
    asyncio.run(seed())
    print("Demo panel: http://0.0.0.0:8080/admin  (login: admin / admin)")
    uvicorn.run(app, host="0.0.0.0", port=8080)
