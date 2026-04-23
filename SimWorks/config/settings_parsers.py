"""Shared helpers for parsing environment variables in settings modules."""

from __future__ import annotations

import os
import re

_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


def bool_from_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def csv_from_env(name: str, default: list[str] | None = None) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return default[:] if default else []
    return [item for item in re.split(r"\s*,\s*", value.strip()) if item]


def int_from_env(name: str, default: int, *, minimum: int | None = None) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        result = default
    else:
        try:
            result = int(value)
        except ValueError as exc:
            raise ValueError(
                f"Environment variable {name} must be an integer, got: {value!r}"
            ) from exc

    if minimum is not None and result < minimum:
        raise ValueError(f"Environment variable {name} must be >= {minimum}, got: {result}")
    return result


def optional_int_from_env(name: str, *, minimum: int | None = None) -> int | None:
    """Return int if the env var is set to a non-blank value, otherwise None."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        result = int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got: {value!r}") from exc
    if minimum is not None and result < minimum:
        raise ValueError(f"Environment variable {name} must be >= {minimum}, got: {result}")
    return result
