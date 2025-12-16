"""Default loader performing minimal configuration and autodiscovery."""

from __future__ import annotations

import glob
import importlib
import os
import sys
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
        for module in self._resolve_modules(modules):
            importlib.import_module(module)
            imported.append(module)
        return imported

    def _resolve_modules(self, modules: Iterable[str]) -> list[str]:
        resolved: list[str] = []
        for module in modules:
            if not module:
                continue
            if self._is_pattern(module):
                resolved.extend(self._expand_pattern(module))
            else:
                resolved.append(module)
        return self._dedupe(resolved)

    def _expand_pattern(self, pattern: str) -> list[str]:
        matches: list[str] = []
        module_path_pattern = pattern.replace(".", os.sep)
        for base in sys.path:
            if not base or not os.path.isdir(base):
                continue
            for suffix in ("", ".py", f"{os.sep}__init__.py"):
                glob_pattern = os.path.join(base, f"{module_path_pattern}{suffix}")
                for candidate in glob.glob(glob_pattern):
                    module_name = self._module_name_from_path(candidate, base)
                    if not module_name:
                        continue
                    if importlib.util.find_spec(module_name) and module_name not in matches:
                        matches.append(module_name)
        return matches

    @staticmethod
    def _module_name_from_path(candidate: str, base_path: str) -> str | None:
        rel_path = os.path.relpath(candidate, base_path)
        if rel_path.startswith(os.pardir):
            return None

        rel_path = rel_path.replace(os.sep, ".")
        for suffix in (".__init__.py", ".py"):
            if rel_path.endswith(suffix):
                rel_path = rel_path[: -len(suffix)]
                break

        rel_path = rel_path.rstrip(".")
        return rel_path or None

    @staticmethod
    def _dedupe(items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered

    @staticmethod
    def _is_pattern(value: str) -> bool:
        return any(char in value for char in "*?[")
