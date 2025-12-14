"""Legacy orchestrai.apps entry point.

This module now aliases :class:`orchestrai.app.OrchestrAI` so that imports
from ``orchestrai.apps`` continue to work while directing users to the
canonical application class.
"""

from __future__ import annotations

from ..app import OrchestrAI as _CoreOrchestrAI, warn_deprecated_apps_import


class OrcaMode(str):
    AUTO = "auto"
    SINGLE = "single_orca"
    POD = "orca_pod"


warn_deprecated_apps_import()

OrchestrAI = _CoreOrchestrAI

__all__ = ("OrchestrAI", "OrcaMode")
