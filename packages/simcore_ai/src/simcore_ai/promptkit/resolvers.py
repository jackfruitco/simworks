# simcore_ai/promptkit/resolvers.py
from __future__ import annotations

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

from typing import Any, Type, TYPE_CHECKING
import logging

from simcore_ai.identity.utils import parse_dot_identity
from simcore_ai.tracing import service_span_sync

from .exceptions import PromptSectionResolutionError

if TYPE_CHECKING:
    from .types import PromptSection

logger = logging.getLogger(__name__)


def resolve_section(entry: Any) -> Type["PromptSection"]:
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
    # Local imports to avoid import cycles
    from .registry import PromptRegistry
    from .types import PromptSection

    entry_type = type(entry).__name__
    preview = None
    try:
        if isinstance(entry, str):
            preview = entry[:120]
        elif isinstance(entry, tuple):
            preview = str(entry)
        else:
            preview = getattr(entry, "__name__", None) or getattr(entry, "__class__", type(entry)).__name__
    except Exception:
        preview = None

    with service_span_sync(
        "ai.prompt.resolve_section",
        attributes={
            "entry.type": entry_type,
            "entry.preview": preview,
        },
    ):
        # Tuple identity (namespace, kind, name)
        if isinstance(entry, tuple) and len(entry) == 3:
            o, b, n = entry
            if not all(isinstance(p, str) and p for p in (o, b, n)):
                raise PromptSectionResolutionError(
                    "tuple identity must be (namespace, kind, name) with non-empty strings"
                )
            try:
                return PromptRegistry.require((o, b, n))
            except Exception as exc:
                raise PromptSectionResolutionError(
                    f"failed to resolve section identity tuple: {(o, b, n)}"
                ) from exc

        # String identity (dot-only)
        if isinstance(entry, str):
            try:
                o, b, n = parse_dot_identity(entry)
                return PromptRegistry.require((o, b, n))
            except Exception as exc:
                raise PromptSectionResolutionError(
                    f"failed to resolve section identity '{entry}' (dot-only)"
                ) from exc

        # Direct class provided
        if isinstance(entry, type) and issubclass(entry, PromptSection):
            return entry

        # Instance provided -> return its class
        if isinstance(entry, PromptSection):
            return entry.__class__

        raise PromptSectionResolutionError(
            f"unsupported prompt section entry type: {type(entry).__name__} (supported: str (dot identity), tuple3, PromptSection class or instance)"
        )
