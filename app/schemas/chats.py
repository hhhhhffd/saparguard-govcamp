from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class SourceCreate(BaseModel):
    telegram_chat_id: int | None = None
    username: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=512)
    load_history: bool = True
    history_limit: int | None = Field(default=1000, ge=1)
    collect_from_date: datetime | None = None

    @model_validator(mode="after")
    def require_identifier(self) -> "SourceCreate":
        if self.telegram_chat_id is None and not self.username:
            raise ValueError("telegram_chat_id or username is required")
        return self


class SourceRead(BaseModel):
    id: int
    telegram_chat_id: int | None
    username: str | None
    title: str | None
    chat_type: str
    is_active: bool
    load_history: bool
    history_limit: int | None
    collect_from_date: datetime | None
    history_requested_at: datetime | None
    last_synced_at: datetime | None
    last_error: str | None
    message_count: int = 0
    last_message_at: datetime | None = None
