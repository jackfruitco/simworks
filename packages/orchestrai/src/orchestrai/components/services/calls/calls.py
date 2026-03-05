from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from orchestrai.utils.json import make_json_safe

JsonPrimitive = str | int | float | bool | None


def assert_jsonable(value: Any, *, path: str = "root") -> None:
    """Raise ``TypeError`` if *value* cannot be represented in JSON.

    Note: datetime values should be pre-coerced to strings via _coerce()
    before calling this function. Raw datetime objects will fail validation.
    """

    def _check(val: Any, prefix: str) -> None:
        if isinstance(val, (str, int, float, bool)) or val is None:
            return
        if isinstance(val, dict):
            for key, inner in val.items():
                _check(inner, f"{prefix}.{key}")
            return
        if isinstance(val, (list, tuple)):
            for idx, inner in enumerate(val):
                _check(inner, f"{prefix}[{idx}]")
            return
        raise TypeError(f"{prefix} is not JSON serializable (type={type(val).__name__})")

    _check(value, path)


def _coerce(value: Any) -> JsonPrimitive | dict[str, Any] | list[Any]:
    """Coerce a value to JSON-serializable form using the shared utility."""
    return make_json_safe(value)


@dataclass
class ServiceCall:
    """Lightweight execution record for service tasks."""

    id: str
    status: str
    input: Any
    context: dict[str, Any] | None
    result: Any | None
    error: str | None
    dispatch: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    service: str | None = None
    request: Any | None = field(default=None, repr=False, compare=False)
    # Token tracking
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("request", None)
        payload = {key: _coerce(val) for key, val in payload.items()}
        assert_jsonable(payload)
        return payload


def to_jsonable(call: ServiceCall) -> dict[str, Any]:
    return call.to_jsonable()


__all__ = ["ServiceCall", "assert_jsonable", "to_jsonable"]
