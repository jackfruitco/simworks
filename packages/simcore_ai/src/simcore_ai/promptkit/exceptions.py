# simcore_ai/promptkit/exceptions.py
from __future__ import annotations

from simcore_ai.exceptions.base import SimCoreError
from simcore_ai.exceptions.registry_exceptions import RegistryError


class PromptKitError(SimCoreError): ...

class PromptResolutionError(PromptKitError, RegistryError):
    """Raised when a prompt cannot be resolved from a prompt template."""


class PromptPlanResolutionError(PromptResolutionError):
    """Raised when a prompt plan cannot be resolved from a prompt template."""


class PromptSectionNotFoundError(PromptPlanResolutionError):
    """Raised when a prompt section cannot be resolved from a plan entry."""


class DuplicatePromptSectionIdentityError(Exception):
    """Raised when a prompt section identity is already taken by a different class."""
    ...
