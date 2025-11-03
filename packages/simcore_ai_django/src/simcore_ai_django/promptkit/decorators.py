from __future__ import annotations

"""
Django-aware prompt section decorator (class-based, no factories).

This decorator composes the **core** prompt-section decorator with the Django
base decorator so that identity resolution and registration are consistent with
the centralized Identity system:

- Identity is **derived via resolver and stamped onto the class** (`cls.identity = Identity(...)`) prior to registration.
- Sets the domain default `kind="prompt_section"` when none is provided.
- Registers the class with the Django prompt-sections **registry** (`prompt_sections`),
  which enforces duplicate/collision policy (see `SIMCORE_COLLISIONS_STRICT`).

Notes
-----
- This decorator **stamps** a resolved `identity: Identity` on the class (it does not stamp legacy `namespace/kind/name` fields). Collisions are handled by the registry.
"""

from typing import Any

from simcore_ai.promptkit.decorators import (
    PromptSectionRegistrationDecorator as CorePromptSectionDecorator,
)
from simcore_ai_django.decorators.base import DjangoBaseDecorator


class DjangoPromptSectionDecorator(CorePromptSectionDecorator, DjangoBaseDecorator):
    """Django-aware prompt section decorator:
    - identity resolution via DjangoBaseDecorator (resolver-backed, no stamping)
    - registry wiring to `prompt_sections`
    - stamps `cls.identity` before calling registry.register(cls)
    """

    # Domain default for kind (used only if the caller/class supplies none)
    default_kind = "prompt_section"

    def derive_identity(self, cls, *, namespace=None, kind=None, name=None):
        # Defer to the core PromptSectionRegistrationDecorator to apply default kind='prompt_section'
        return CorePromptSectionDecorator.derive_identity(self, cls, namespace=namespace, kind=kind, name=name)

    def get_registry(self) -> Any | None:  # narrow protocol: must expose .register(cls)
        """Return the Django prompt-sections registry singleton."""
        from .registry import prompts
        return prompts


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
