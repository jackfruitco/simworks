# packages/simcore_ai/src/simcore_ai/codecs/decorators.py
from __future__ import annotations

"""
Core (non-Django) codec decorator built on the class-based BaseDecorator.

- Uses the shared, framework-agnostic identity derivation helpers.
- Attaches a finalized Identity to the class:
    * cls.identity      -> (namespace, kind, name) tuple
    * cls.identity_obj  -> Identity dataclass
- No registration in core: get_registry() returns None, so decoration is
  derivation-only. The Django layer provides registration and collision policy.

Domain default:
- kind defaults to "codec" when neither decorator args nor class attributes
  provide a value.
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


class CodecRegistrationDecorator(BaseDecorator):
    """Core codec decorator: derive identity; no registration in core."""

    def get_registry(self):
        # Core layer does not register codecs. Django layer overrides this.
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
        Derive (namespace, kind, name) with 'codec' as the domain default for kind.
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

        # 3) kind (domain default = "codec")
        kd = derive_kind(cls, kind_arg=kind, kind_attr=kind_attr, default="codec")

        # 4) validate
        validate_identity(ns, kd, nm)

        return Identity(namespace=ns, kind=kd, name=nm)


# Ready-to-use decorator instances (short and namespaced aliases)
codec = CodecRegistrationDecorator()
ai_codec = codec

__all__ = ["codec", "ai_codec", "CodecRegistrationDecorator"]
