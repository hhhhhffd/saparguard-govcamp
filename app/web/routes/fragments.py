from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.database.repositories import MessageRepository, SourceRepository
from app.database.session import get_session
from app.web.routes.pages import DEFAULT_PAGE_SIZE, message_page_context
from app.web.templating import templates

router = APIRouter(prefix="/ui/fragments")


@router.get("/messages", response_class=HTMLResponse)
async def messages_table(
    request: Request,
    limit: int = DEFAULT_PAGE_SIZE,
    append: bool = False,
    cursor_sent_at: datetime | None = None,
    cursor_id: int | None = None,
    query: str | None = None,
    chat_id: int | None = None,
    sender_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    message_type: str | None = None,
    entity_query: str | None = None,
    analysis_status: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    context = await message_page_context(
        limit=min(max(limit, 1), 100),
        cursor_sent_at=cursor_sent_at,
        cursor_id=cursor_id,
        query=query,
        chat_id=chat_id,
        sender_id=sender_id,
        date_from=date_from,
        date_to=date_to,
        message_type=message_type,
        entity_query=entity_query,
        analysis_status=analysis_status,
        session=session,
    )
    context["request"] = request
    context["display_timezone"] = settings.display_timezone
    template_name = "partials/message_rows.html" if append else "partials/messages_table.html"
    response = templates.TemplateResponse(request, template_name, context)
    if not append:
        response.headers["HX-Push-Url"] = str(context["page_url"])
    return response


@router.get("/sources", response_class=HTMLResponse)
async def sources_table(
    request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/sources_table.html",
        {"sources": await SourceRepository(session).list()},
    )


@router.get("/messages/{message_id}", response_class=HTMLResponse)
async def message_detail(
    message_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> HTMLResponse:
    message = await MessageRepository(session).get(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return templates.TemplateResponse(request, "partials/message_detail.html", {"message": message})
