from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel

JsonPrimitive = str | int | float | bool | None


def assert_jsonable(value: Any, *, path: str = "root") -> None:
    """Raise ``TypeError`` if *value* cannot be represented in JSON."""

    def _check(val: Any, prefix: str) -> None:
        if isinstance(val, (str, int, float, bool)) or val is None:
            return
        if isinstance(val, datetime):
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
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return _coerce(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    return value  # primitives and None pass through


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

    def to_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload = {key: _coerce(val) for key, val in payload.items()}
        assert_jsonable(payload)
        return payload


def to_jsonable(call: ServiceCall) -> dict[str, Any]:
    return call.to_jsonable()


__all__ = ["ServiceCall", "assert_jsonable", "to_jsonable"]
