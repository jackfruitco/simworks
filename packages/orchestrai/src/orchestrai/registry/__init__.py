"""Lightweight registries."""
from __future__ import annotations

from .simple import Registry


class BaseRegistry(Registry):
    """Compatibility shim for legacy decorators."""


# Basic registries kept for compatibility with provider toolkit.
provider_backends = Registry()
providers = Registry()
codecs = Registry()

__all__ = ["Registry", "BaseRegistry", "provider_backends", "providers", "codecs"]
