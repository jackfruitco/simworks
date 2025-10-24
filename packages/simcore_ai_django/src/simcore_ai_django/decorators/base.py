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

logger = logging.getLogger(__name__)


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
    ) -> tuple[Identity, dict[str, Any] | None]:
        """
        Derive and validate Identity using Django-aware helpers.

        Precedence:
          - name: explicit arg/attr preserved (trim only) OR derived from class name
          - namespace: arg -> class attr -> app label -> app name -> module root
          - kind: arg -> class attr -> self.default_kind (domain-specific)

        Stripping:
          - Apply case-insensitive, edge-only token stripping to **derived names only**
            using tokens from the owning AppConfig (and optional global settings).
          - If stripping empties the name, fall back to the normalized class name.
        """
        fqcn = f"{cls.__module__}.{cls.__name__}"
        trace_meta: dict[str, Any] = {}

        # Gather any class-level attributes
        ns_attr = getattr(cls, "namespace", None)
        kind_attr = getattr(cls, "kind", None)
        name_attr = getattr(cls, "name", None)

        # 1) namespace (Django-aware)
        ns = derive_namespace_django(
            cls,
            namespace_arg=namespace,
            namespace_attr=ns_attr,
        )

        # 2) kind (domain default via subclass attribute)
        kd = derive_kind(cls, kind_arg=kind, kind_attr=kind_attr) or self.default_kind

        # 3) name (explicit preserved; derived -> lower + tokens)
        explicit = (name is not None) or (name_attr is not None)
        raw_name = derive_name(
            cls,
            name_arg=name,
            name_attr=name_attr,
            derived_lower=True,
        )
        tokens_used: tuple[str, ...] = ()
        if explicit:
            nm = normalize_name(raw_name)
            post_strip = raw_name  # no stripping performed for explicit names
            trace_meta["ai.identity.name.explicit"] = True

        else:
            tokens_used = get_app_tokens_for_name(cls)
            trace_meta.update({
                "ai.identity.name.stripped_tokens": ",".join(tokens_used),
                "ai.identity.name.stripped_tokens_list": list(tokens_used),
            })
            logger.debug("Using tokens %s for %s", tokens_used, fqcn)
            stripped = strip_name_tokens_django(raw_name, tokens=tokens_used)
            post_strip = stripped or raw_name
            # Guard: if stripping produces empty, fall back to normalized class name
            nm = normalize_name(post_strip or cls.__name__)

        # Defensive: avoid redundant namespace prefix in name (e.g., "chatlab-…")
        ns_prefix = f"{ns}-"
        if nm.startswith(ns_prefix):
            nm = nm[len(ns_prefix):]

        # 4) validate & return
        validate_identity(ns, kd, nm)
        ident = Identity(namespace=ns, kind=kd, name=nm)

        # Debug meta for tracing (consumed by BaseDecorator.__call__ after registration)
        trace_meta.update({
            # who/what
            "ai.class": fqcn,

            # tuple3 snapshots for easy diffing
            "ai.tuple3.raw": f"{ns}.{kd}.{raw_name}",
            "ai.tuple3.post_strip": f"{ns}.{kd}.{post_strip}",
            "ai.tuple3.post_norm": f"{ns}.{kd}.{nm}",

            # explicit vs derived flag
            "ai.identity.name.explicit": bool(explicit),

            # resolution breadcrumbs (flattened; avoid nested dicts for OTEL)
            "ai.identity.namespace.attr": ns_attr or "",
            "ai.identity.namespace.arg": namespace or "",
            "ai.identity.namespace.derived": ns or "",

            "ai.identity.kind.attr": kind_attr or "",
            "ai.identity.kind.arg": kind or "",
            "ai.identity.kind.derived": kd or "",

            "ai.identity.name.attr": name_attr or "",
            "ai.identity.name.arg": name or "",
            "ai.identity.name.post_strip": post_strip or "",
            "ai.identity.name.derived": nm or "",
        })

        return ident, trace_meta
