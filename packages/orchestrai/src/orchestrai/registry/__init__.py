"""Lightweight registries."""
from __future__ import annotations

from .base import BaseRegistry, ComponentRegistry
from .simple import AppRegistry
from .singletons import codecs, prompt_sections, provider_backends, providers

__all__ = [
    "AppRegistry",
    "BaseRegistry",
    "ComponentRegistry",
    "provider_backends",
    "providers",
    "codecs",
    "prompt_sections",
]
