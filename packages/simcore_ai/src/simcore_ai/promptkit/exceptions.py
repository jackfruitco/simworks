# simcore_ai/promptkit/exceptions.py
from __future__ import annotations

from simcore_ai.exceptions.base import SimCoreError


class PromptResolutionError(SimCoreError, RuntimeError):
    """Raised when a prompt cannot be resolved from a prompt template."""


class PromptPlanResolutionError(PromptResolutionError):
    """Raised when a prompt plan cannot be resolved from a prompt template."""


class PromptSectionResolutionError(PromptPlanResolutionError):
    """Raised when a prompt section cannot be resolved from a plan entry."""
