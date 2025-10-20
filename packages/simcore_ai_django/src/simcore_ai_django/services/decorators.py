# simcore_ai_django/services/decorators.py
"""Django-aware LLM service decorator.

This module composes the Django identity/tokens mixins with the **core**
service registration decorator to provide a drop-in `@llm_service` that:

- Supports decorating **classes and async functions** (function targets are
  wrapped into a `BaseLLMService` subclass by the core decorator).
- Resolves identity using Django-aware defaults (AppConfig-aware) while
  preserving the core precedence rules:
    kwargs > class attrs > Django/module defaults
- Strips affix tokens from the **name only** (case-insensitive, both ends,
  iterative) using merged sources (core defaults + env + Django settings +
  AppConfig contributions).
- Registers services with the core `ServiceRegistry` and enforces tuple³
  uniqueness. Collisions are handled by the decorator via hyphen-int suffixing
  on the **name** (`name-2`, `-3`, ...), with WARNING logs; import-time never
  crashes.

No Django imports are required here beyond the mixins module, which is designed
to be import-safe even when Django settings/apps are not initialized yet.
"""
from __future__ import annotations

import logging

from simcore_ai.services.decorators import ServiceRegistrationDecorator
from simcore_ai_django.decorators.mixins import DjangoSimcoreIdentityMixin

log = logging.getLogger(__name__)


class DjangoServiceRegistrationDecorator(DjangoSimcoreIdentityMixin, ServiceRegistrationDecorator):
    """Django-aware service decorator.

    Inherits:
      - Identity resolution and token merging from `DjangoSimcoreIdentityMixin`.
      - Function wrapping, extras binding, and collision-handling registration
        from `ServiceRegistrationDecorator`.
    """
    # At this point, the core behavior is sufficient. If we later need
    # Django-specific extras (e.g., default execution backend), we can
    # override `bind_extras` here and read from Django settings safely.
    pass


# Ready-to-use instance for Django apps
llm_service = DjangoServiceRegistrationDecorator()

__all__ = ["llm_service", "DjangoServiceRegistrationDecorator"]
