# simcore_ai/decorators/__init__.py
"""Decorator facade (lazy imports to avoid cycles).

This package exposes the base registration decorator and *optionally* the
domain-specific decorator classes/instances via **lazy** attribute access.
We avoid importing domain modules (services, codecs, promptkit, schemas)
at import time to prevent circular imports during early Django startup.
"""
from __future__ import annotations

from .base import BaseDecorator
from .components import *

__all__ = [
    "BaseDecorator",
    "codec",
    "service",
    "schema",
    "prompt_section"
]

