# simcore_ai_django/promptkit/decorators.py
"""Django-aware prompt section decorator.

This module composes the Django identity/tokens mixins with the **core**
prompt section decorator to provide a drop-in `@prompt_section` that:

- Supports decorating **classes only** (prompt sections must be classes).
  Function targets are rejected by the core decorator with a clear `TypeError`.
- Resolves identity using Django-aware defaults (AppConfig-aware) while
  preserving the core precedence rules:
    kwargs > class attrs > Django/module defaults
- Strips affix tokens from the **name only** (case-insensitive, both ends,
  iterative) using merged sources (core defaults + env + Django settings +
  AppConfig contributions).
- Registers prompt sections with the core `PromptRegistry` and enforces tuple³
  uniqueness. Collisions are handled by the decorator via hyphen-int suffixing
  on the **name** (`name-2`, `-3`, ...), with WARNING logs; import-time never
  crashes.

No heavy Django imports are required here beyond the safe mixins module.
"""
from __future__ import annotations

import logging
from typing import Optional, Type, Any

from simcore_ai.promptkit.decorators import PromptSectionDecorator
from simcore_ai_django.decorators.mixins import DjangoSimcoreIdentityMixin

logger = logging.getLogger(__name__)


class DjangoPromptSectionDecorator(DjangoSimcoreIdentityMixin, PromptSectionDecorator):
    """Django-aware prompt section decorator.

    Inherits:
      - Identity resolution and token merging from `DjangoSimcoreIdentityMixin`.
      - Class-only enforcement and collision-handling registration from
        `PromptSectionDecorator`.
    """
    pass


class DjangoPromptScenarioDecorator(DjangoSimcoreIdentityMixin, PromptSectionDecorator):
    """Django-aware prompt section decorator.

    Inherits:
      - Identity resolution and token merging from `DjangoSimcoreIdentityMixin`.
      - Class-only enforcement and collision-handling registration from
        `PromptScenarioDecorator`.
    """

    def log_custom(self, cls: Optional[Type[Any]] = None, *args: Any, **kwargs: Any) -> None:
        logger.warning("DjangoPromptScenarioDecorator is not implemented yet. "
                       "Deferring to DjangoPromptSectionDecorator instead.")


# Ready-to-use instance for Django apps
prompt_section = DjangoPromptSectionDecorator()
prompt_scenario = DjangoPromptScenarioDecorator()

__all__ = [
    "prompt_section", "DjangoPromptSectionDecorator",
    "prompt_scenario", "DjangoPromptScenarioDecorator"
]
