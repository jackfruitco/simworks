"""Lightweight registries."""
from __future__ import annotations

from .base import BaseRegistry
from .simple import Registry
from .singletons import codecs, prompt_sections, provider_backends, providers

__all__ = [
    "Registry",
    "BaseRegistry",
    "provider_backends",
    "providers",
    "codecs",
    "prompt_sections",
]
