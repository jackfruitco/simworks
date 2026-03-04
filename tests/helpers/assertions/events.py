from __future__ import annotations

from collections.abc import Iterable


def assert_event_envelope_fields(payload: dict[str, object], required_fields: Iterable[str]) -> None:
    missing = [field for field in required_fields if field not in payload]
    assert not missing, f"Event envelope missing required fields: {missing}"
