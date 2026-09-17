"""Run only admin panel (for local testing)."""

import uvicorn
from app.config import get_settings
from app.web.app import app
from app.database.session import create_database
import app.web.deps as web_deps

settings = get_settings()
db = create_database(settings.database_url, echo=settings.sql_echo)
web_deps._db = db

if __name__ == "__main__":
    uvicorn.run(app, host=settings.admin_panel_host, port=settings.admin_panel_port)
