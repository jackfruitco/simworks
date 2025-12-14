"""Legacy orchestrai.apps entry point.

This module now aliases :class:`orchestrai.app.OrchestrAI` so that imports
from ``orchestrai.apps`` continue to work while directing users to the
canonical application class.
"""

from __future__ import annotations

import warnings

from ..app import OrchestrAI as _CoreOrchestrAI


class OrcaMode(str):
    AUTO = "auto"
    SINGLE = "single_orca"
    POD = "orca_pod"


warnings.warn(
    "'orchestrai.apps.OrchestrAI' is deprecated; import 'OrchestrAI' from the "
    "top-level 'orchestrai' package instead.",
    DeprecationWarning,
    stacklevel=2,
)

OrchestrAI = _CoreOrchestrAI

__all__ = ("OrchestrAI", "OrcaMode")
