# packages/simcore_ai_django/src/simcore_ai_django/schemas/registry.py
from __future__ import annotations

"""
Django response schema registry (facade).

This module delegates to the core registry in
`simcore_ai.schemas.registry` so identity handling and storage live
in one place. Keeping a Django-facing facade preserves import paths
(e.g., `simcore_ai_django.schemas.registry`) without duplicating logic.

Exports:
- SchemaRegistry: alias of the core ResponseSchemaRegistry
- schemas: Django-layer singleton instance
"""

from simcore_ai.schemas.registry import (
    ResponseSchemaRegistry as _CoreResponseSchemaRegistry,
)

# Public alias for Django callers
SchemaRegistry = _CoreResponseSchemaRegistry

__all__ = [
    "SchemaRegistry",
    "schemas",
]

# Django-layer singleton
schemas = SchemaRegistry()