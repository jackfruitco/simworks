"""Loader interfaces used for configuration and autodiscovery."""

from __future__ import annotations

from typing import Iterable


class BaseLoader:
    """Base loader responsible for configuration and module discovery."""

    def read_configuration(self, app) -> None:
        raise NotImplementedError

    def import_default_modules(self, app) -> None:
        raise NotImplementedError

    def autodiscover(self, app, modules: Iterable[str]) -> list[str]:
        raise NotImplementedError

