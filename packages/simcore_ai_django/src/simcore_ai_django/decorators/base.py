# packages/simcore_ai_django/src/simcore_ai_django/decorators/base.py
from __future__ import annotations

"""
Django-aware base decorator (class-based, no factories).

This decorator extends the core `BaseDecorator` with Django-specific identity
behavior:

- `namespace` derivation prefers Django app *label*, then app *name*, then the
  module root (core fallback).
- *Name-only* token stripping using per-app tokens (from `AppConfig.IDENTITY_STRIP_TOKENS`)
  and optional global tokens (`settings.SIMCORE_IDENTITY_STRIP_TOKENS_GLOBAL`).
- Domain defaults for `kind` are provided by subclasses via `default_kind`.

Registration policy is **not** implemented here; domain decorators in this
package override `get_registry()` to return the appropriate singleton registry.

IMPORTANT:
- This module must not import or depend on any core Django models/ORM.
- Collision handling lives in registries; this class exposes
  `allow_collision_rewrite()` as a hook (default: False) for the registry to
  consult when `SIMCORE_COLLISIONS_STRICT == False`.
"""

from typing import Any, Optional, Type
import logging

from simcore_ai.decorators.base import BaseDecorator
from simcore_ai.decorators.helpers import (
    derive_name,
    derive_kind,
    normalize_name,
    validate_identity,
)
from simcore_ai.identity.base import Identity

from simcore_ai_django.decorators.helpers import (
    derive_namespace_django,
    get_app_tokens_for_name,
    strip_name_tokens_django,
)

log = logging.getLogger(__name__)


class DjangoBaseDecorator(BaseDecorator):
    """Django-aware identity pipeline; registration deferred to domain subclasses."""

    #: Subclasses should override this to set a domain default for `kind`
    #: (e.g., "codec", "service", "prompt_section", "schema").
    default_kind: str = "default"

    def get_registry(self):
        """By default, no registry is bound at the base level (domain overrides)."""
        return None

    # --- collision policy hook -------------------------------------------------
    def allow_collision_rewrite(self) -> bool:
        """
        Hint for registries when `SIMCORE_COLLISIONS_STRICT` is false: if this
        returns True, a registry MAY apply a deterministic rename (e.g., `name-2`).
        Default is False; do not enable in production.
        """
        return False

    # --- identity derivation ---------------------------------------------------
    def derive_identity(
            self,
            cls: Type[Any],
            *,
            namespace: Optional[str],
            kind: Optional[str],
            name: Optional[str],
    ) -> Identity:
        """
        Derive and validate Identity using Django-aware helpers.

        Precedence:
          - name: explicit arg/attr preserved (trim only) OR derived from class name
          - namespace: arg -> class attr -> app label -> app name -> module root
          - kind: arg -> class attr -> self.default_kind (domain-specific)

        Stripping:
          - Apply case-insensitive, segment-aware token stripping to **name only**
            using tokens from the owning AppConfig (and optional global settings).
        """
        # Gather any class-level attributes
        ns_attr = getattr(cls, "namespace", None)
        kind_attr = getattr(cls, "kind", None)
        name_attr = getattr(cls, "name", None)

        # 1) name (explicit preserved; derived -> lower)
        nm = derive_name(cls, name_arg=name, name_attr=name_attr, derived_lower=True)
        # tokens come from the Django app + optional global list
        tokens = get_app_tokens_for_name(cls)
        nm = strip_name_tokens_django(nm, tokens=tokens)
        nm = normalize_name(nm)

        # 2) namespace (Django-aware)
        ns = derive_namespace_django(
            cls, namespace_arg=namespace, namespace_attr=ns_attr
        )

        # 3) kind (domain default via subclass attribute)
        kd = derive_kind(
            cls, kind_arg=kind, kind_attr=kind_attr, default=self.default_kind
        )

        # 4) validate & return
        validate_identity(ns, kd, nm)
        return Identity(namespace=ns, kind=kd, name=nm)
