"""Canonical serialization helpers for Pydantic models in OrchestrAI Django.

Centralises the ``model_dump`` / MockValSer fallback logic that was previously
duplicated across ``tasks.py`` and ``signals.py``.

Public API
----------
pydantic_model_to_dict(obj)
    Best-effort conversion of a Pydantic model (or any object) to a plain
    JSON-safe dict.  Falls back to manual field extraction when Pydantic AI's
    internal ``MockValSer`` validator is active (typically in tests).
"""

from __future__ import annotations

from typing import Any


def pydantic_model_to_dict(obj: Any) -> dict:
    """Convert *obj* to a JSON-safe dict.

    Tries ``model_dump(mode="json")`` first.  Falls back to recursive field
    extraction when that raises ``TypeError`` (e.g. Pydantic AI's
    ``MockValSer`` test utility overrides the serialiser and breaks the normal
    path).  Other ``TypeError`` causes are re-raised.

    Args:
        obj: A Pydantic ``BaseModel`` instance, dict, or any object.

    Returns:
        A plain dict suitable for JSON serialisation.
    """
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    # Standard Pydantic v2 path
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError as exc:
            if "MockValSer" not in str(exc):
                raise
            # MockValSer fallback — extract fields manually
            return _extract_fields(obj)

    # Legacy Pydantic v1
    dct = getattr(obj, "dict", None)
    if callable(dct):
        return dct()

    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)

    return {"value": repr(obj)}


def _extract_fields(obj: Any) -> dict:
    """Recursively extract Pydantic model fields without calling model_dump.

    Used only when ``model_dump`` raises due to ``MockValSer``.
    """
    from orchestrai.utils.json import make_json_safe

    if not hasattr(obj, "model_fields"):
        return {"value": make_json_safe(obj)}

    result: dict[str, Any] = {}
    for field_name in obj.model_fields:
        try:
            value = getattr(obj, field_name, None)
            if hasattr(value, "model_fields"):
                result[field_name] = _extract_fields(value)
            elif isinstance(value, list):
                result[field_name] = [
                    _extract_fields(item) if hasattr(item, "model_fields") else make_json_safe(item)
                    for item in value
                ]
            elif isinstance(value, dict):
                result[field_name] = {
                    k: _extract_fields(v) if hasattr(v, "model_fields") else make_json_safe(v)
                    for k, v in value.items()
                }
            else:
                result[field_name] = make_json_safe(value)
        except Exception:
            result[field_name] = None

    return result
