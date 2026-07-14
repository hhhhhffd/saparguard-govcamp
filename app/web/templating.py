from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.core.config import settings
from app.web.i18n import t

templates = Jinja2Templates(directory="app/web/templates")


def format_display_datetime(value: datetime | None) -> str:
    """Render timezone-aware database timestamps in the configured UI timezone."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        raise ValueError("Display datetime must be timezone-aware")
    return value.astimezone(ZoneInfo(settings.display_timezone)).strftime("%H:%M:%S %d.%m.%Y")


templates.env.filters["display_datetime"] = format_display_datetime
templates.env.globals["t"] = t
