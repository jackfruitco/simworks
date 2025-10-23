# packages/simcore_ai_django/src/simcore_ai_django/promptkit/decorators.py
from __future__ import annotations

"""
Django-aware prompt section decorator (class-based, no factories).

This decorator composes the core domain decorator with the Django-aware base to:

- derive a finalized Identity `(namespace, kind, name)` using Django-aware
  namespace resolution (AppConfig label → app name → module root) and
  name-only token stripping from AppConfig/global settings,
- set the domain default `kind="prompt_section"`,
- register the class with the Django prompt-sections registry (`prompt_sections`),
  which enforces duplicate vs collision policy controlled by
  `SIMCORE_COLLISIONS_STRICT`.

No collision rewriting is performed here; registries own policy. If you want to
opt-in to dev-only rename-on-collision, override `allow_collision_rewrite()` in
this subclass to return True (recommended OFF in production).
"""

from typing import Any

from simcore_ai.promptkit.decorators import (
    PromptSectionRegistrationDecorator as CorePromptSectionDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator
from simcore_ai_django.promptkit.registry import prompt_sections


class DjangoPromptSectionDecorator(DjangoBaseDecorator, CorePromptSectionDecorator):
    """Django-aware prompt section decorator: identity via DjangoBaseDecorator; registry wired here."""

    # Domain default for kind
    default_kind = "prompt_section"

    def get_registry(self) -> Any | None:
        """Return the Django prompt sections registry singleton."""
        return prompt_sections


# Ready-to-use decorator instances (short and namespaced aliases)
prompt_section = DjangoPromptSectionDecorator()
ai_prompt_section = prompt_section

__all__ = ["prompt_section", "ai_prompt_section", "DjangoPromptSectionDecorator"]
