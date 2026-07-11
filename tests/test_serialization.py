from datetime import datetime, timezone

from app.collector.serialization import to_jsonable


def test_to_jsonable_converts_datetime_and_bytes() -> None:
    value = {"when": datetime(2026, 7, 11, tzinfo=timezone.utc), "content": b"abc"}

    result = to_jsonable(value)

    assert result["when"] == "2026-07-11T00:00:00+00:00"
    assert result["content"] == {"type": "bytes", "length": 3}
