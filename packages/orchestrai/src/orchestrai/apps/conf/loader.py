# orchestrai/apps/conf/loader.py

import importlib
import os
from dataclasses import dataclass, field
from typing import Any, Mapping
from functools import lru_cache

from .models import OrcaDiscoverySettings, OrcaSettings


def _import_from_path(path: str) -> Any:
    """
    Import "pkg.module:attr" or "pkg.module.attr" into a Python object.
    """
    if ":" in path:
        mod_path, attr = path.split(":", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    # Try dotted attribute on module
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        mod_path = ".".join(parts[:i])
        try:
            mod = importlib.import_module(mod_path)
        except Exception:
            continue
        attr_path = parts[i:]
        obj: Any = mod
        for a in attr_path:
            obj = getattr(obj, a)
        return obj
    raise ImportError(f"Could not import from path: {path}")


def _deep_merge(a: dict[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """
    Merge b into a (recursive for dicts). Returns a (mutated).
    """
    for k, v in b.items():
        if isinstance(v, Mapping) and isinstance(a.get(k), dict):
            _deep_merge(a[k], v)
        else:
            a[k] = v
    return a


def _extract_namespaced_settings(obj: Any, namespace: str) -> dict[str, Any]:
    """
    Supports two shapes:
    1) settings has attribute ORCA = {...}
    2) settings has ORCA_* attributes that become keys

    Returned dict uses canonical keys (e.g. MODE, PROVIDERS, CLIENTS, DISCOVERY)
    """
    ns = namespace.upper()
    out: dict[str, Any] = {}

    # ORCA = {...}
    if hasattr(obj, ns):
        v = getattr(obj, ns)
        if isinstance(v, Mapping):
            out = _deep_merge(out, dict(v))

    # ORCA_* = ...
    prefix = ns + "_"
    for key in dir(obj):
        if not key.startswith(prefix):
            continue
        # e.g. ORCA_MODE -> MODE
        short = key[len(prefix):]
        out[short] = getattr(obj, key)

    return out


def _env_to_settings(namespace: str) -> dict[str, Any]:
    """
    Minimal env support:
      ORCA_MODE=single_orca
      ORCA_NAME=myproj

    You can extend this later for JSON blobs, etc.
    """
    ns = namespace.upper()
    out: dict[str, Any] = {}
    for k, v in os.environ.items():
        if not k.startswith(ns + "_"):
            continue
        short = k[len(ns) + 1 :]
        if short in ("MODE", "NAME"):
            out[short] = v
    return out


@dataclass(slots=True)
class SettingsLoader:
    """
    Collects sources; resolves to one OrcaSettings object.

    Precedence order (last wins):
      defaults < mapping sources < object sources < env source
    """
    _mapping_sources: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)
    _object_sources: list[tuple[str, str]] = field(default_factory=list)  # (obj_path, namespace)
    _env_sources: list[str] = field(default_factory=list)  # namespaces
    _component_dirs: list[str] = field(default_factory=list)
    _discovery_modules: list[str] = field(default_factory=list)

    def add_mapping_source(self, *, mapping: Mapping[str, Any], namespace: str) -> None:
        self._mapping_sources.append((namespace, mapping))

    def add_object_source(self, *, obj_path: str, namespace: str) -> None:
        self._object_sources.append((obj_path, namespace))

    def add_env_source(self, *, namespace: str) -> None:
        self._env_sources.append(namespace)

    def add_component_dirs(self, dirs: list[str]) -> None:
        self._component_dirs.extend(dirs)

    def add_discovery_modules(self, module_names: list[str]) -> None:
        self._discovery_modules.extend(module_names)

    def resolve(self) -> OrcaSettings:
        merged: dict[str, Any] = {}

        # 1) mapping sources
        for namespace, mapping in self._mapping_sources:
            _deep_merge(merged, _extract_namespaced_settings(type("Tmp", (), {namespace.upper(): mapping})(), namespace))

        # 2) object sources (e.g. "django.conf:settings" OR "myproj.settings")
        for obj_path, namespace in self._object_sources:
            obj = _import_from_path(obj_path)
            extracted = _extract_namespaced_settings(obj, namespace)
            _deep_merge(merged, extracted)

        # 3) env sources
        for namespace in self._env_sources:
            _deep_merge(merged, _env_to_settings(namespace))

        # Apply “extra discovery modules/dirs” collected imperatively
        disc = dict(merged.get("DISCOVERY", {}) or {})
        if self._component_dirs:
            extra_dirs = list(disc.get("extra_component_dirs", []))
            extra_dirs.extend(self._component_dirs)
            disc["extra_component_dirs"] = extra_dirs

        if self._discovery_modules:
            mods = list(disc.get("modules", []))
            mods.extend(self._discovery_modules)
            disc["modules"] = mods

        if disc:
            merged["DISCOVERY"] = disc

        # Normalize DISCOVERY to model
        if "DISCOVERY" in merged and isinstance(merged["DISCOVERY"], Mapping):
            merged["DISCOVERY"] = OrcaDiscoverySettings(**dict(merged["DISCOVERY"]))

        return OrcaSettings(**merged)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Backwards-compatible type alias for older call sites.
OrchestraiSettings = OrcaSettings


@lru_cache(maxsize=8)
def get_settings(
    *,
    namespace: str = "ORCHESTRAI",
    obj_path: str | None = "django.conf:settings",
) -> OrcaSettings:
    """Load and cache OrchestrAI settings.

    This replaces the old `orchestrai.apps.conf.runtime` module.

    Sources (last wins):
      - object source (by default: `django.conf:settings`)
      - environment variables (`{NAMESPACE}_*`)
    """
    loader = SettingsLoader()

    if obj_path:
        loader.add_object_source(obj_path=obj_path, namespace=namespace)

    loader.add_env_source(namespace=namespace)

    return loader.resolve()


def clear_settings_cache() -> None:
    """Clear the cached settings (useful for tests)."""
    get_settings.cache_clear()