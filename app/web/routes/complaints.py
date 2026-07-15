"""Citizen complaint submission and staff handling screens."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import current_user
from app.database.models import (
    AppUser,
    Complaint,
    ComplaintStatus,
    ComplaintStatusHistory,
    UserRole,
)
from app.database.session import get_session
from app.web.i18n import translate
from app.web.templating import templates

router = APIRouter(prefix="/complaints")
PAGE_SIZE = 25
MAX_COMPLAINT_LOCATION_LENGTH = 500
COMPLAINT_TOPICS = (
    "dangerous_driving",
    "traffic_violation",
    "road_infrastructure",
    "illegal_parking",
    "other",
)


def _is_staff(user: AppUser) -> bool:
    return user.role in (UserRole.WORKER.value, UserRole.ADMIN.value)


def _require_citizen(user: AppUser) -> None:
    if user.role != UserRole.CITIZEN.value:
        raise HTTPException(status_code=403, detail="Only citizens can submit complaints")


def _complaint_form_context(
    request: Request,
    *,
    error_key: str | None = None,
    subject: str = "",
    description: str = "",
    location_text: str = "",
) -> dict[str, object]:
    locale = request.state.locale
    return {
        "error": translate(error_key, locale) if error_key else "",
        "subject": subject,
        "description": description,
        "location_text": location_text,
        "complaint_topics": COMPLAINT_TOPICS,
    }


@router.get("", response_class=HTMLResponse)
async def complaints_list(
    request: Request,
    status: str | None = Query(default=None),
    query: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    statement = select(Complaint, AppUser.email).join(AppUser, Complaint.author_id == AppUser.id)
    if not _is_staff(user):
        statement = statement.where(Complaint.author_id == user.id)
    if status in {item.value for item in ComplaintStatus}:
        statement = statement.where(Complaint.status == status)
    if query and _is_staff(user):
        query_value = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                AppUser.normalized_email.ilike(query_value),
                Complaint.subject.ilike(query_value),
                Complaint.description.ilike(query_value),
            )
        )
    total = await session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = (
        await session.execute(
            statement.order_by(Complaint.created_at.desc(), Complaint.id.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "pages/complaints.html",
        {
            "complaints": rows,
            "is_staff": _is_staff(user),
            "statuses": list(ComplaintStatus),
            "filters": {"status": status or "", "query": query or "", "page": page},
            "pagination": {"page": page, "has_more": page * PAGE_SIZE < total, "total": total},
            "complaint_topics": COMPLAINT_TOPICS,
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def complaint_create_page(
    request: Request, user: AppUser = Depends(current_user)
) -> HTMLResponse:
    _require_citizen(user)
    return templates.TemplateResponse(request, "pages/complaint_form.html", _complaint_form_context(request))


@router.post("/new", response_class=HTMLResponse, response_model=None)
async def complaint_create(
    request: Request,
    subject: str = Form(...),
    description: str = Form(...),
    location_text: str | None = Form(default=None),
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse | HTMLResponse:
    _require_citizen(user)
    subject = subject.strip()
    description = description.strip()
    location_text = location_text.strip() if location_text else ""
    if subject not in COMPLAINT_TOPICS:
        return templates.TemplateResponse(
            request,
            "pages/complaint_form.html",
            _complaint_form_context(
                request,
                error_key="complaints.error_subject_invalid",
                subject=subject,
                description=description,
                location_text=location_text,
            ),
            status_code=422,
        )
    if not description:
        return templates.TemplateResponse(
            request,
            "pages/complaint_form.html",
            _complaint_form_context(
                request,
                error_key="complaints.error_description_required",
                subject=subject,
                description=description,
                location_text=location_text,
            ),
            status_code=422,
        )
    if len(location_text) > MAX_COMPLAINT_LOCATION_LENGTH:
        return templates.TemplateResponse(
            request,
            "pages/complaint_form.html",
            _complaint_form_context(
                request,
                error_key="complaints.error_location_too_long",
                subject=subject,
                description=description,
                location_text=location_text,
            ),
            status_code=422,
        )
    now = datetime.now(timezone.utc)
    async with session.begin():
        complaint = Complaint(
            author_id=user.id,
            subject=subject,
            description=description,
            location_text=location_text or None,
            status=ComplaintStatus.NEW.value,
            created_at=now,
            updated_at=now,
        )
        session.add(complaint)
        await session.flush()
        session.add(
            ComplaintStatusHistory(
                complaint_id=complaint.id,
                old_status=None,
                new_status=ComplaintStatus.NEW.value,
                changed_by_id=user.id,
                changed_at=now,
            )
        )
    return RedirectResponse(f"/complaints/{complaint.id}", status_code=303)


@router.get("/{complaint_id}", response_class=HTMLResponse)
async def complaint_detail(
    complaint_id: int,
    request: Request,
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    complaint = await session.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    is_staff = _is_staff(user)
    if not is_staff and complaint.author_id != user.id:
        raise HTTPException(status_code=403, detail="Complaint does not belong to current user")
    author = await session.get(AppUser, complaint.author_id)
    history_rows = (
        await session.execute(
            select(ComplaintStatusHistory, AppUser.email)
            .outerjoin(AppUser, ComplaintStatusHistory.changed_by_id == AppUser.id)
            .where(ComplaintStatusHistory.complaint_id == complaint_id)
            .order_by(ComplaintStatusHistory.changed_at.desc())
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "pages/complaint_detail.html",
        {
            "complaint": complaint,
            "author": author,
            "history": history_rows,
            "is_staff": is_staff,
            "statuses": list(ComplaintStatus),
            "complaint_topics": COMPLAINT_TOPICS,
        },
    )


@router.post("/{complaint_id}/status")
async def change_complaint_status(
    complaint_id: int,
    status: str = Form(...),
    user: AppUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    if not _is_staff(user):
        raise HTTPException(status_code=403, detail="Only staff can change complaint status")
    if status not in {item.value for item in ComplaintStatus}:
        raise HTTPException(status_code=422, detail="Invalid complaint status")
    async with session.begin():
        complaint = await session.get(Complaint, complaint_id)
        if complaint is None:
            raise HTTPException(status_code=404, detail="Complaint not found")
        if complaint.status != status:
            now = datetime.now(timezone.utc)
            session.add(
                ComplaintStatusHistory(
                    complaint_id=complaint.id,
                    old_status=complaint.status,
                    new_status=status,
                    changed_by_id=user.id,
                    changed_at=now,
                )
            )
            complaint.status = status
            complaint.status_changed_by_id = user.id
            complaint.updated_at = now
    return RedirectResponse(f"/complaints/{complaint_id}", status_code=303)
