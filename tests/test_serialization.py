from types import SimpleNamespace

from telethon.tl import types

from app.collector.serialization import message_values


def test_message_values_keeps_only_compact_forward_metadata() -> None:
    message = SimpleNamespace(
        id=42,
        sender_id=11,
        message="text",
        date=None,
        fwd_from=SimpleNamespace(from_id=types.PeerUser(99), from_name="Forwarded sender", post_author=None),
        media=None,
        edit_date=None,
    )

    values = message_values(message, -100123)

    assert values["forward_source_id"] == 99
    assert values["forward_source_name"] == "Forwarded sender"
    assert "raw_data" not in values
    assert "views" not in values
