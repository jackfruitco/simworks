# simcore_ai/components/promptkit/resolvers.py


from ..exceptions import ComponentNotFoundError
from ...identity import Identity, IdentityLike
from ...registry.exceptions import RegistryNotFoundError

"""
Resolver utilities for PromptSections (AIv3).

- Accepts dot identity strings ("namespace.kind.name"), tuple3 identities (namespace, kind, name),
  or a direct PromptSection subclass/instance.
- Normalizes to a PromptSection *class* so callers can instantiate uniformly.
- No legacy colon identities, no role-paired plans.

Typical usage from services:
    SectionCls = resolve_section("chatlab.patient.initial")
    section = SectionCls(context={...})
"""

from typing import Type, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .base import PromptSection

logger = logging.getLogger(__name__)


def resolve_section(entry: IdentityLike) -> Type["PromptSection"]:
    """Resolve a plan entry into a PromptSection *class*.

    Accepted forms:
      - str: canonical identity "namespace.kind.name" (dot-only)
      - tuple3: (namespace, kind, name) with non-empty strings
      - class: a PromptSection subclass (returned as-is)
      - instance: a PromptSection instance (its class is returned)

    Returns:
        The PromptSection class to instantiate at call time.

    Notes
    -----
    • Legacy colon identities and role-paired specs are not supported.
  """
    try:
        return Identity.resolve.for_("PromptSection", entry)
    except (RegistryNotFoundError, ComponentNotFoundError):
        pass

    try:
        return PromptSection.get(entry)
    except (RegistryNotFoundError, ComponentNotFoundError):
        pass

    # fallback to core registry
    from simcore_ai.registry import prompt_sections
    try:
        ident = Identity.get_for(entry)
        return type(prompt_sections.get(ident))
    except (RegistryNotFoundError, ComponentNotFoundError):
        pass

    raise ComponentNotFoundError(entry)
