from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import SourceRepository
from app.database.session import get_session
from app.web.templating import templates

router = APIRouter(prefix="/ui/actions")


async def sources_action_response(
    request: Request, session: AsyncSession
) -> HTMLResponse | RedirectResponse:
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request,
            "partials/sources_table.html",
            {"sources": await SourceRepository(session).list()},
        )
    return RedirectResponse(url="/sources", status_code=303)


@router.post("/sources", response_class=HTMLResponse, response_model=None)
async def create_source(
    request: Request,
    identifier: str = Form(...),
    load_history: bool = Form(default=True),
    history_limit: int | None = Form(default=1000),
    collect_from_date: datetime | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    normalized_identifier = identifier.strip().lstrip("@")
    if not normalized_identifier:
        raise HTTPException(status_code=422, detail="Источник обязателен")
    values: dict[str, object] = {
        "telegram_chat_id": int(normalized_identifier)
        if normalized_identifier.lstrip("-").isdigit()
        else None,
        "username": None if normalized_identifier.lstrip("-").isdigit() else normalized_identifier,
        "title": None,
        "load_history": load_history,
        "history_limit": history_limit,
        "collect_from_date": collect_from_date,
    }
    async with session.begin():
        await SourceRepository(session).create(**values)
    return await sources_action_response(request, session)


@router.post("/sources/{source_id}/{action}", response_class=HTMLResponse, response_model=None)
async def source_action(
    source_id: int,
    action: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    repository = SourceRepository(session)
    async with session.begin():
        if action == "enable":
            source = await repository.set_active(source_id, True)
        elif action == "disable":
            source = await repository.set_active(source_id, False)
        elif action == "history":
            source = await repository.request_history(source_id)
        elif action == "remove":
            removed = await repository.remove(source_id)
            source = object() if removed else None
        else:
            raise HTTPException(status_code=404, detail="Action not found")
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return await sources_action_response(request, session)
