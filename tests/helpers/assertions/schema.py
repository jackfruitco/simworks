from __future__ import annotations

from collections.abc import Iterable


def assert_schema_has_paths(schema: dict[str, object], required_paths: Iterable[str]) -> None:
    paths = schema.get("paths") or {}
    missing = [path for path in required_paths if path not in paths]
    assert not missing, f"OpenAPI schema missing required paths: {missing}"
