from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image
from starlette.requests import Request
from sqlalchemy.dialects import postgresql

from app.collector.history import message_is_within_history_window
from app.core.enums import MediaJobStatus
from app.database.repositories.messages import MessageRepository
from app.processing.media.plate_recognizer import normalize_plate
from app.processing.media.image_processor import save_optimized_image
from app.database.repositories.media_jobs import MediaJobRepository
from app.web import templating
from app.web.routes import fragments
from app.web.templating import templates


def test_history_window_rejects_old_messages() -> None:
    assert message_is_within_history_window(datetime.now(timezone.utc))
    assert not message_is_within_history_window(datetime.now(timezone.utc) - timedelta(days=8))


def test_normalize_plate_removes_formatting() -> None:
    assert normalize_plate("a 123 bc-02") == "A123BC02"


@pytest.mark.asyncio
async def test_existing_media_file_does_not_create_another_job() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    await MediaJobRepository(session).create_pending(
        10, source_kind="photo", original_mime_type="image/jpeg"
    )

    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_failed_job_is_scheduled_for_retry() -> None:
    session = AsyncMock()
    job = SimpleNamespace(id=1, media_file_id=2, attempts=1)

    await MediaJobRepository(session).fail(
        job, "download failed", max_attempts=3, retry_delay_seconds=60
    )

    statements = [call.args[0] for call in session.execute.await_args_list]
    update_values = {column.key: value.value for column, value in statements[-1]._values.items()}
    assert update_values["status"] == MediaJobStatus.PENDING
    assert update_values["next_retry_at"] is not None


@pytest.mark.asyncio
async def test_stale_processing_job_is_returned_to_queue() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)

    recovered = await MediaJobRepository(session).recover_stale_jobs(timeout_seconds=900)

    assert recovered == 1
    statement = session.execute.await_args_list[0].args[0]
    assert "processing" in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_mark_deleted_updates_existing_messages() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 2
    session.execute = AsyncMock(return_value=result)

    count = await MessageRepository(session).mark_deleted(-100123, [1, 2])

    assert count == 2
    assert session.commit.await_count == 0


@pytest.mark.asyncio
async def test_repeated_message_uses_postgresql_upsert() -> None:
    session = AsyncMock()
    saved_result = MagicMock()
    saved_result.scalar_one.return_value = SimpleNamespace(id=1)
    session.scalar = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=saved_result)

    await MessageRepository(session).upsert_message(
        {
            "telegram_chat_id": -100123,
            "telegram_message_id": 77,
            "telegram_sender_id": None,
            "text": "message",
            "published_at": datetime.now(timezone.utc),
            "saved_at": datetime.now(timezone.utc),
            "is_forwarded": False,
            "forward_source_id": None,
            "forward_source_name": None,
            "media_type": None,
            "edited_at": None,
            "is_deleted": False,
            "deleted_at": None,
        },
        save_edit=False,
    )

    statement = session.execute.await_args.args[0]
    assert "ON CONFLICT" in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_concurrent_claims_use_skip_locked_leases() -> None:
    def session_for(job_id: int) -> AsyncMock:
        session = AsyncMock()
        lease_result = MagicMock()
        lease_result.one_or_none.return_value = SimpleNamespace(id=job_id, media_file_id=job_id)
        loaded_result = MagicMock()
        loaded_result.scalar_one.return_value = SimpleNamespace(id=job_id)
        session.execute = AsyncMock(side_effect=[lease_result, MagicMock(), loaded_result])
        return session

    first_session, second_session = session_for(1), session_for(2)
    first, second = await asyncio.gather(
        MediaJobRepository(first_session).claim_next_job(),
        MediaJobRepository(second_session).claim_next_job(),
    )

    assert {first.id, second.id} == {1, 2}
    for session in (first_session, second_session):
        statement = session.execute.await_args_list[0].args[0]
        assert "FOR UPDATE SKIP LOCKED" in str(statement)


def test_telegram_text_is_escaped_by_jinja() -> None:
    message = SimpleNamespace(
        id=1,
        published_at=datetime.now(timezone.utc),
        chat=SimpleNamespace(title="chat"),
        telegram_chat_id=-100123,
        sender=None,
        text="<script>alert(1)</script>",
        media_type=None,
        is_deleted=False,
        edited_at=None,
    )

    rendered = templates.get_template("partials/messages_table.html").render(
        messages=[message], has_more=False
    )

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_display_datetime_uses_configured_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(templating.settings, "display_timezone", "UTC")

    result = templating.format_display_datetime(datetime(2026, 7, 12, 8, 5, 3, tzinfo=timezone.utc))

    assert result == "08.05.03 12.07.2026"


@pytest.mark.asyncio
async def test_messages_fragment_pushes_a_full_page_url(monkeypatch: pytest.MonkeyPatch) -> None:
    context = {
        "messages": [],
        "has_more": False,
        "next_cursor": None,
        "filters": {"limit": 50, "query": "taxi"},
        "next_page_query": "limit=50&query=taxi",
        "page_url": "/messages?limit=50&query=taxi",
    }
    monkeypatch.setattr(fragments, "message_page_context", AsyncMock(return_value=context))
    request = Request({"type": "http", "method": "GET", "path": "/ui/fragments/messages"})

    response = await fragments.messages_table(request, query="taxi", session=MagicMock())

    assert response.headers["HX-Push-Url"] == "/messages?limit=50&query=taxi"


def test_image_processing_uses_unique_temporary_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media_root = tmp_path / "media"
    first_source = tmp_path / "first" / "photo.png"
    second_source = tmp_path / "second" / "photo.png"
    first_source.parent.mkdir()
    second_source.parent.mkdir()
    Image.new("RGB", (8, 8), "red").save(first_source)
    Image.new("RGB", (8, 8), "blue").save(second_source)
    monkeypatch.setattr(templating.settings, "media_storage_path", media_root)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save_optimized_image, (first_source, second_source)))

    assert {path for _, path in results} == {
        media_root / f"{values['sha256']}.jpg" for values, _ in results
    }
    assert not list(media_root.glob(".processing-*"))
