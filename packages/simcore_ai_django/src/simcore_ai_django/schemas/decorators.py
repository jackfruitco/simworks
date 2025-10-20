# simcore_ai_django/schemas/decorators.py
"""Django-aware response schema decorator.

This module composes the Django identity/tokens mixins with the **core**
response schema decorator to provide a drop-in `@response_schema` that:

- Supports decorating **classes only** (schemas must be classes). Function
  targets are rejected by the core decorator with a clear `TypeError`.
- Resolves identity using Django-aware defaults (AppConfig-aware) while
  preserving the core precedence rules:
    kwargs > class attrs > Django/module defaults
- Strips affix tokens from the **name only** (case-insensitive, both ends,
  iterative) using merged sources (core defaults + env + Django settings +
  AppConfig contributions).
- Registers schemas with the core `ResponseSchemaRegistry` and enforces tuple³
  uniqueness. Collisions are handled by the decorator via hyphen-int suffixing
  on the **name** (`name-2`, `-3`, ...), with WARNING logs; import-time never
  crashes.

No heavy Django imports are required here beyond the safe mixins module.
"""
from __future__ import annotations

import logging

from simcore_ai.schemas.decorators import ResponseSchemaDecorator
from simcore_ai_django.decorators.mixins import DjangoSimcoreIdentityMixin

log = logging.getLogger(__name__)


class DjangoResponseSchemaDecorator(DjangoSimcoreIdentityMixin, ResponseSchemaDecorator):
    """Django-aware response schema decorator.

    Inherits:
      - Identity resolution and token merging from `DjangoSimcoreIdentityMixin`.
      - Class-only enforcement and collision-handling registration from
        `ResponseSchemaDecorator`.
    """
    pass


# Ready-to-use instance for Django apps
response_schema = DjangoResponseSchemaDecorator()

__all__ = ["response_schema", "DjangoResponseSchemaDecorator"]
