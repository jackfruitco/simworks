# simcore_ai/promptkit/exceptions.py
from __future__ import annotations

from simcore_ai.exceptions.base import SimCoreError


class PromptSectionResolutionError(SimCoreError, RuntimeError):
    """Raised when a prompt section cannot be resolved from a plan entry."""
