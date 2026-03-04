from __future__ import annotations

from pathlib import Path

import pytest

_LANE_MARKERS = {"unit", "component", "integration", "contract", "system", "e2e"}


def _has_lane_marker(item: pytest.Item) -> bool:
    return any(item.get_closest_marker(marker) for marker in _LANE_MARKERS)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = Path(str(getattr(item, "path", getattr(item, "fspath", "")))).as_posix()
        if (
            "packages/orchestrai/tests/" in path or "packages/orchestrai_django/tests/" in path
        ) and not item.get_closest_marker("contract"):
            item.add_marker(pytest.mark.contract)
        if item.get_closest_marker("django_db"):
            if not item.get_closest_marker("integration"):
                item.add_marker(pytest.mark.integration)
            continue
        if not _has_lane_marker(item):
            item.add_marker(pytest.mark.unit)
