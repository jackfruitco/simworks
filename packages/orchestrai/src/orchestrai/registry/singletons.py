"""Backwards-compatible registry singletons."""

from .active_app import (
    codecs,
    prompt_sections,
    provider_backends,
    providers,
    schemas,
    services,
)

__all__ = [
    "codecs",
    "prompt_sections",
    "provider_backends",
    "providers",
    "schemas",
    "services",
]
