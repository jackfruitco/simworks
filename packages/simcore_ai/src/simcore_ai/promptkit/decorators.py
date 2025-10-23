# packages/simcore_ai/src/simcore_ai/promptkit/decorators.py
from __future__ import annotations

"""
Core (non-Django) Prompt Section decorator built on the class-based BaseDecorator.

This module defines the **core** `prompt_section` decorator using the shared,
framework-agnostic `BaseDecorator`. It is responsible only for:

- deriving a finalized Identity (namespace, kind, name) using core helpers
  with the domain default `kind="prompt_section"`,
- attaching the identity to the decorated class as:
    * cls.identity      -> (namespace, kind, name) tuple
    * cls.identity_obj  -> Identity dataclass instance
- deferring registration: in the core package, `get_registry()` returns None,
  so decoration skips registration (Django layer wires registries and policy).

IMPORTANT:
- No Django imports here.
- No dynamic registrar lookups.
- No collision handling; that lives in the Django registries.
"""

from typing import Any, Optional, Type

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.decorators.helpers import (
    derive_name,
    derive_namespace_core,
    derive_kind,
    strip_name_tokens,
    normalize_name,
    validate_identity,
)
from simcore_ai.identity.base import Identity


class PromptSectionRegistrationDecorator(BaseDecorator):
    """Core Prompt Section decorator: derive identity; no registration in core."""

    def get_registry(self):
        # Core layer does not register prompt sections. Django layer overrides this.
        return None

    def derive_identity(
            self,
            cls: Type[Any],
            *,
            namespace: Optional[str],
            kind: Optional[str],
            name: Optional[str],
    ) -> Identity:
        """
        Derive (namespace, kind, name) with 'prompt_section' as the domain default for kind.
        Token stripping is not applied at the core layer unless tokens are provided;
        here we pass none (Django overrides add per-app tokens on name).
        """
        ns_attr = getattr(cls, "namespace", None)
        kind_attr = getattr(cls, "kind", None)
        name_attr = getattr(cls, "name", None)

        # 1) name
        nm = derive_name(cls, name_arg=name, name_attr=name_attr, derived_lower=True)
        nm = strip_name_tokens(nm, tokens=())  # core: no tokens
        nm = normalize_name(nm)

        # 2) namespace
        ns = derive_namespace_core(cls, namespace_arg=namespace, namespace_attr=ns_attr)

        # 3) kind (domain default = "prompt_section")
        kd = derive_kind(cls, kind_arg=kind, kind_attr=kind_attr, default="prompt_section")

        # 4) validate
        validate_identity(ns, kd, nm)

        return Identity(namespace=ns, kind=kd, name=nm)


# Ready-to-use decorator instances (short and namespaced aliases)
prompt_section = PromptSectionRegistrationDecorator()
ai_prompt_section = prompt_section

__all__ = ["prompt_section", "ai_prompt_section", "PromptSectionRegistrationDecorator"]
