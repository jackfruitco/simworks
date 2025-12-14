# orcheestrai/apps/discovery.py

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Any

from .conf.models import OrcaSettings


@dataclass(slots=True)
class DiscoveryResult:
    imported: list[str]
    components: dict[str, Any]


def _safe_import(module_path: str) -> bool:
    """
    Import module if it exists.

    Returns True if imported. Returns False if module doesn't exist.
    Raises if the module exists but throws during import (real bug).
    """
    spec = importlib.util.find_spec(module_path)
    if spec is None:
        return False
    importlib.import_module(module_path)
    return True


def autodiscover(*, settings: OrcaSettings) -> DiscoveryResult:
    """
    Non-Django autodiscovery.

    Strategy:
    - For each app in DISCOVERY.apps
    - For each module in DISCOVERY.modules
      try importing "{app}.{module}"
    - Also import any absolute module paths in DISCOVERY.extra_modules
    """
    imported: list[str] = []

    disc = settings.DISCOVERY

    # Absolute modules
    for mod in disc.extra_modules:
        if _safe_import(mod):
            imported.append(mod)

    # App-relative modules
    for app_pkg in disc.apps:
        for mod in disc.modules:
            module_path = f"{app_pkg}.{mod}"
            if _safe_import(module_path):
                imported.append(module_path)

    # NOTE: actual component registration should happen as side effects of imports
    # via your decorators/registries. Here we only report imports.
    return DiscoveryResult(imported=imported, components={})
