from __future__ import annotations

"""
Django schema registry (facade).

This module intentionally delegates to the core registry in
`simcore_ai.schemas.registry` so that identity resolution and storage
live in a single place.

Why a facade?
- Keeps imports stable for Django callers (`simcore_ai_django.schemas.registry`)
- Avoids code/config drift between core and Django layers
- Honors the centralized Identity system (IdentityMixin + resolvers)

Exports:
- SchemaRegistry: the core registry class
- register_schema: decorator alias to core helper
"""

from typing import Iterable, Optional, Type

# Import the core primitives and re-expose them here
from simcore_ai.schemas.registry import (  # noqa: F401
    ResponseSchemaRegistry as _CoreSchemaRegistry,
)

# Public aliases (Django callers can continue to import from this module)
SchemaRegistry = _CoreSchemaRegistry

__all__ = [
    "SchemaRegistry",
    "schemas",
]

# Singleton instance for Django layer
schemas = SchemaRegistry()
