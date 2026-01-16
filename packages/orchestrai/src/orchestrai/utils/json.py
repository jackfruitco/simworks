# orchestrai/utils/json.py
"""Centralized JSON serialization utilities for OrchestrAI.

This module provides consistent JSON serialization across all OrchestrAI components,
handling non-JSON-serializable types like UUID, Decimal, datetime, etc.

Usage:
    # Pre-convert a value before json.dumps
    safe_data = make_json_safe(data)
    json_str = json.dumps(safe_data)

    # Or use as default handler for json.dumps
    json_str = json.dumps(data, default=json_default)
"""

from datetime import datetime, date, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def make_json_safe(value: Any) -> Any:
    """
    Recursively convert non-JSON-serializable types to JSON-safe equivalents.

    Supported conversions:
    - UUID -> str
    - datetime/date/time -> ISO format string
    - timedelta -> total_seconds (float)
    - Decimal -> str (preserves precision)
    - Enum -> value
    - bytes -> UTF-8 string (with replacement for invalid chars)
    - BaseModel -> model_dump(mode="json")
    - dict -> recursive conversion with string keys
    - list/tuple/set -> recursive conversion to list

    Args:
        value: Any Python value to convert

    Returns:
        JSON-serializable equivalent of the input value
    """
    # JSON primitives pass through
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # UUID -> string
    if isinstance(value, UUID):
        return str(value)

    # datetime types -> ISO format
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()

    # timedelta -> seconds
    if isinstance(value, timedelta):
        return value.total_seconds()

    # Decimal -> string (preserves precision)
    if isinstance(value, Decimal):
        return str(value)

    # Enum -> underlying value
    if isinstance(value, Enum):
        return value.value

    # bytes -> UTF-8 string
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    # Pydantic models -> use mode="json" for proper serialization
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    # dict -> recursive with string keys
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in value.items()}

    # Sequences -> recursive to list
    if isinstance(value, (list, tuple, set, frozenset)):
        return [make_json_safe(v) for v in value]

    # Fallback: try __dict__ for objects, otherwise str()
    if hasattr(value, "__dict__"):
        return make_json_safe(value.__dict__)

    return str(value)


def json_default(value: Any) -> Any:
    """
    Default handler for json.dumps(default=json_default).

    Use this as the `default` parameter to json.dumps() to automatically
    handle non-JSON-serializable types.

    Args:
        value: The value that json.dumps couldn't serialize

    Returns:
        JSON-serializable equivalent

    Raises:
        TypeError: If value truly cannot be serialized (after conversion attempt)

    Example:
        >>> import json
        >>> from uuid import uuid4
        >>> data = {"id": uuid4()}
        >>> json.dumps(data, default=json_default)
        '{"id": "..."}'
    """
    result = make_json_safe(value)
    # If make_json_safe returned the same object unchanged and it's not a primitive,
    # that means we couldn't convert it
    if result is value and not isinstance(value, (str, int, float, bool, type(None))):
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
    return result
