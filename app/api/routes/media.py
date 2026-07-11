from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.repositories import MediaRepository
from app.database.session import get_session

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{media_file_id}")
async def get_media_file(media_file_id: int, session: AsyncSession = Depends(get_session)) -> FileResponse:
    media_file = await MediaRepository(session).get_file(media_file_id)
    if media_file is None or media_file.relative_path is None:
        raise HTTPException(status_code=404, detail="Media file not available")
    media_root = settings.media_storage_path.resolve()
    path = (settings.media_storage_path.parent / media_file.relative_path).resolve()
    if media_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Media file not available")
    return FileResponse(path, media_type=media_file.mime_type or "image/jpeg")
