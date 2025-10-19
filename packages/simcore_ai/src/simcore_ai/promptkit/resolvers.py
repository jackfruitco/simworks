# simcore_ai/promptkit/resolvers.py
from __future__ import annotations

"""
Resolver utilities for PromptSections (AIv3).

- Accepts dot identity strings ("origin.bucket.name"), tuple3 identities (origin, bucket, name),
  or a direct PromptSection subclass/instance.
- Normalizes to a PromptSection *class* so callers can instantiate uniformly.
- No legacy colon identities, no role-paired plans.

Typical usage from services:
    SectionCls = resolve_section("chatlab.patient.initial")
    section = SectionCls(context={...})
"""

from typing import Any, Type
import logging

from simcore_ai.identity.utils import parse_dot_identity

from .exceptions import PromptSectionResolutionError

logger = logging.getLogger(__name__)


def resolve_section(entry: Any) -> Type["PromptSection"]:
    """Resolve a plan entry into a PromptSection *class*.

    Accepted forms:
      - str: canonical identity "origin.bucket.name" (dot-only)
      - tuple3: (origin, bucket, name) with non-empty strings
      - class: a PromptSection subclass (returned as-is)
      - instance: a PromptSection instance (its class is returned)

    Returns:
        The PromptSection class to instantiate at call time.
    """
    # Local imports to avoid import cycles
    from .registry import PromptRegistry
    from .types import PromptSection

    # Tuple identity (origin, bucket, name)
    if isinstance(entry, tuple) and len(entry) == 3:
        o, b, n = entry
        if not all(isinstance(p, str) and p for p in (o, b, n)):
            raise PromptSectionResolutionError("tuple identity must be (origin, bucket, name) with non-empty strings")
        try:
            return PromptRegistry.require((o, b, n))
        except Exception as exc:
            raise PromptSectionResolutionError(f"failed to resolve section identity tuple: {(o, b, n)}") from exc

    # String identity (dot-only)
    if isinstance(entry, str):
        try:
            o, b, n = parse_dot_identity(entry)
            return PromptRegistry.require((o, b, n))
        except Exception as exc:
            raise PromptSectionResolutionError(f"failed to resolve section identity '{entry}' (dot-only)") from exc

    # Direct class provided
    if isinstance(entry, type) and issubclass(entry, PromptSection):
        return entry

    # Instance provided -> return its class
    if isinstance(entry, PromptSection):
        return entry.__class__

    raise PromptSectionResolutionError(
        f"unsupported prompt section entry type: {type(entry).__name__} (supported: str (dot identity), tuple3, PromptSection class or instance)"
    )
