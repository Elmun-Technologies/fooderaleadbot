"""Run only admin panel (for local testing)."""

import uvicorn
from app.config import get_settings
from app.web.app import app
from app.database.session import create_database
import app.web.deps as web_deps

settings = get_settings()
db = create_database(settings.database_url, echo=settings.sql_echo)
web_deps._db = db

# Ensure follow-up templates on startup
@app.on_event("startup")
async def _ensure_templates():
    from app.database.repository import LeadRepository
    from app.services.followup_service import FollowUpService

    async with db.session() as session:
        repo = LeadRepository(session)
        service = FollowUpService(None, repo)
        await service.ensure_default_templates()

if __name__ == "__main__":
    uvicorn.run(app, host=settings.admin_panel_host, port=settings.admin_panel_port)
