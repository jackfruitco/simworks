# orchestrai/contrib/provider_backends/__init__.py
from __future__ import annotations

from typing import Literal, Final

ProviderKind = Literal[
    "openai",
    # "anthropic",
    # "vertex",
    # "azure_openai",
    # "local",
]

AVAILABLE_PROVIDER_BACKENDS: Final[tuple[str, ...]] = (
    "openai",
    # "anthropic",
    # "vertex",
    # "azure_openai",
    # "local",
)

__all__ = [
    "ProviderKind", "AVAILABLE_PROVIDER_BACKENDS",
]
