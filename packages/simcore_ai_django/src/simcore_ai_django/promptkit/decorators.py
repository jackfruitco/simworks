# packages/simcore_ai_django/src/simcore_ai_django/promptkit/decorators.py
from __future__ import annotations

"""
Django-aware prompt section decorator (class-based, no factories).

This decorator composes the **core** prompt-section decorator with the Django
base decorator so that identity resolution and registration are consistent with
the centralized Identity system:

- Identity is **derived via resolver** (no class attribute stamping). For Django,
  the namespace preference is: decorator arg → class attr → AppConfig.label →
  module root → "default". Name derivation applies Django-aware strip tokens.
- Sets the domain default `kind="prompt_section"` when none is provided.
- Registers the class with the Django prompt-sections **registry** (`prompt_sections`),
  which enforces duplicate/collision policy (see `SIMCORE_COLLISIONS_STRICT`).

Notes
-----
- This decorator does **not** mutate `namespace/kind/name` on your class.
  It relies on resolvers and registries that operate on `identity.as_tuple3`
  and `identity.as_str` obtained from the class via the mixins/resolvers.
- Collision rewriting is not performed here. Registries own the policy.
  If you want to opt-in to dev-only rename-on-collision, override
  `allow_collision_rewrite()` in the base decorator subclass (recommended OFF
  in production).
"""

from typing import Any

from simcore_ai.promptkit.decorators import (
    PromptSectionRegistrationDecorator as CorePromptSectionDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator
from simcore_ai_django.promptkit.registry import prompt_sections


class DjangoPromptSectionDecorator(DjangoBaseDecorator, CorePromptSectionDecorator):
    """Django-aware prompt section decorator:
    - identity resolution via DjangoBaseDecorator (resolver-backed, no stamping)
    - registry wiring to `prompt_sections`
    """

    # Domain default for kind (used only if the caller/class supplies none)
    default_kind = "prompt_section"

    def get_registry(self) -> Any | None:  # narrow protocol: must expose .register(cls)
        """Return the Django prompt-sections registry singleton."""
        return prompt_sections


# Ready-to-use decorator instances (short and namespaced aliases)
prompt_section = DjangoPromptSectionDecorator()
ai_prompt_section = prompt_section

# Historical alias; scenarios are sections in AIv3
prompt_scenario = prompt_section

__all__ = [
    "prompt_section",
    "ai_prompt_section",
    "prompt_scenario",
    "DjangoPromptSectionDecorator",
]
