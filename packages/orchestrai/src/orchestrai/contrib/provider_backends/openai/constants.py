"""OpenAI provider backend constants.

Centralized constants for the OpenAI Responses API provider backend.
"""
from typing import Final, Literal

from orchestrai.conf import DEFAULTS

# Provider identification
PROVIDER_NAME: Final[Literal["openai"]] = "openai"
API_SURFACE: Final[Literal["responses"]] = "responses"
API_VERSION: Final[None] = None

# Default configuration
DEFAULT_TIMEOUT_S: Final[int | float] = DEFAULTS.get("PROVIDER_DEFAULT_TIMEOUT", 30.0)
DEFAULT_MODEL: Final[str] = DEFAULTS.get("PROVIDER_DEFAULT_MODEL", "gpt-4o-mini")

__all__ = [
    "PROVIDER_NAME",
    "API_SURFACE",
    "API_VERSION",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_MODEL",
]
