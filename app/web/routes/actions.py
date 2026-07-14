from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProfileResolutionConflict, TelegramMessage
from app.database.repositories import SourceRepository
from app.database.session import get_session
from app.review.service import save_annotation
from app.web.templating import templates

router = APIRouter(prefix="/ui/actions")


@router.post("/locale", response_class=RedirectResponse)
async def set_locale(locale: str = Form(...), next_url: str = Form("/")) -> RedirectResponse:
    """Persist a deliberate UI language choice while preserving the current URL."""
    if locale not in {"kk", "ru"}:
        raise HTTPException(status_code=422, detail="Unsupported locale")
    if not next_url.startswith("/") or next_url.startswith("//"):
        raise HTTPException(status_code=422, detail="Invalid return URL")
    response = RedirectResponse(url=next_url, status_code=303)
    response.set_cookie("saparguard_locale", locale, max_age=60 * 60 * 24 * 365, samesite="lax")
    return response


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


@router.post("/review/{message_id}", response_class=RedirectResponse)
async def save_review(
    message_id: int,
    status: str = Form(...),
    annotator: str = Form(...),
    expected_message_type: str | None = Form(default=None),
    phones: list[str] = Form(default=[]),
    routes: list[str] = Form(default=[]),
    vehicles: list[str] = Form(default=[]),
    comment: str | None = Form(default=None),
    ids: str = Form(default=""),
    index: int = Form(default=0),
    return_query: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    try:
        async with session.begin():
            message = await session.get(TelegramMessage, message_id)
            if message is None:
                raise HTTPException(status_code=404, detail="Message not found")
            await save_annotation(
                session,
                message_id=message_id,
                status=status,
                annotator=annotator,
                message_type=expected_message_type,
                phones=phones,
                routes=routes,
                vehicles=vehicles,
                comment=comment,
                source_text=message.text,
            )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    queue = [int(value) for value in ids.split(",") if value.isdigit()]
    if queue:
        next_index = min(index + 1, len(queue) - 1)
        suffix = f"&{return_query}" if return_query else ""
        return RedirectResponse(
            f"/review/{queue[next_index]}?ids={ids}&index={next_index}{suffix}", status_code=303
        )
    return RedirectResponse(f"/review/{message_id}", status_code=303)


@router.post("/conflicts/{conflict_id}", response_class=RedirectResponse)
async def decide_conflict(
    conflict_id: int,
    status: str = Form(...),
    decided_by: str = Form(...),
    comment: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if status not in {"reviewed", "dismissed"} or not decided_by.strip():
        raise HTTPException(status_code=422, detail="Invalid conflict decision")
    async with session.begin():
        conflict = await session.get(ProfileResolutionConflict, conflict_id)
        if conflict is None:
            raise HTTPException(status_code=404, detail="Conflict not found")
        conflict.status = status
        conflict.decided_by = decided_by.strip()
        conflict.decision_comment = comment.strip() if comment else None
        conflict.decided_at = datetime.now(timezone.utc)
        conflict.updated_at = conflict.decided_at
    return RedirectResponse(f"/conflicts?status={status}", status_code=303)
