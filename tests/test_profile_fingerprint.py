from app.processing.profiles.fingerprint import fingerprint


def test_profile_fingerprint_is_stable_for_mapping_order() -> None:
    assert fingerprint({"b": [2, 1], "a": {"z": 1}}) == fingerprint({"a": {"z": 1}, "b": [2, 1]})


def test_profile_fingerprint_changes_when_source_changes() -> None:
    assert fingerprint({"message_id": 1, "is_deleted": False}) != fingerprint(
        {"message_id": 1, "is_deleted": True}
    )
