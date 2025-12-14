"""Default loader performing minimal configuration and autodiscovery."""

from __future__ import annotations

import importlib
import os
from typing import Iterable, List

from .base import BaseLoader


class DefaultLoader(BaseLoader):
    def read_configuration(self, app) -> None:
        app.conf.update_from_envvar("ORCHESTRAI_CONFIG_MODULE")

    def import_default_modules(self, app) -> None:
        modules = app.conf.get("DISCOVERY_PATHS", ())
        self.autodiscover(app, modules)

    def autodiscover(self, app, modules: Iterable[str]) -> List[str]:
        imported: list[str] = []
        for module in modules:
            if not module:
                continue
            importlib.import_module(module)
            imported.append(module)
        return imported

