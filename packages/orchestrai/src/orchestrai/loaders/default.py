"""Default loader performing minimal configuration and autodiscovery."""

from __future__ import annotations

import glob
import importlib
import importlib.util
import os
import sys
from typing import Iterable, List, Sequence

from .base import BaseLoader


class DefaultLoader(BaseLoader):
    COMPONENT_SUFFIXES: tuple[str, ...] = (
        "services",
        "codecs",
        "schemas",
        "prompts",
        "prompt_sections",
        "tools",
        "persist",
    )

    def read_configuration(self, app) -> None:
        app.conf.update_from_envvar("ORCHESTRAI_CONFIG_MODULE")

    def import_default_modules(self, app) -> None:
        modules = app.conf.get("DISCOVERY_PATHS", ())
        self.autodiscover(app, modules)

    def autodiscover(self, app, modules: Iterable[str]) -> List[str]:
        imported: list[str] = []
        resolved = self._resolve_modules(modules)
        expanded = self._expand_package_roots(resolved)
        for module in expanded:
            importlib.import_module(module)
            imported.append(module)
        return imported

    def _expand_package_roots(self, modules: Sequence[str]) -> list[str]:
        """Expand package roots to include known component submodules when present.

        This keeps discovery behavior consistent when callers provide only `<pkg>.orca` or `<pkg>.ai`
        (or other package roots) by also importing `<root>.<suffix>` modules if they exist.

        Pattern entries (globs) are left unchanged; they are already expanded by `_resolve_modules`.
        """

        expanded: list[str] = []
        for module in modules:
            if not module:
                continue
            expanded.append(module)

            # If this is a pattern, don't attempt suffix expansion.
            if self._is_pattern(module):
                continue

            try:
                spec = importlib.util.find_spec(module)
            except ModuleNotFoundError:
                spec = None

            # Only expand if it's a package.
            if spec is None or spec.submodule_search_locations is None:
                continue

            for suffix in self.COMPONENT_SUFFIXES:
                child = f"{module}.{suffix}"
                try:
                    if importlib.util.find_spec(child):
                        expanded.append(child)
                except ModuleNotFoundError:
                    continue

        return self._dedupe(expanded)

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
