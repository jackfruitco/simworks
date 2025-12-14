"""Fixup interfaces for framework integrations."""

from __future__ import annotations

from typing import Iterable


class BaseFixup:
    """Hooks called during app lifecycle."""

    def on_app_init(self, app) -> None:  # pragma: no cover - default noop
        return None

    def on_setup(self, app) -> None:  # pragma: no cover - default noop
        return None

    def on_import_modules(self, app, modules: Iterable[str]) -> None:  # pragma: no cover
        return None

    def autodiscover_sources(self, app) -> Iterable[str]:  # pragma: no cover - default empty
        return []

