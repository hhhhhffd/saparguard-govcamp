from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", {"display_timezone": settings.display_timezone})


@router.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "sources.html", {"display_timezone": settings.display_timezone})


@router.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "messages.html", {"display_timezone": settings.display_timezone})
