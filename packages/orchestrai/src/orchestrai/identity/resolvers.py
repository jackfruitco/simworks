# orchestrai/identity/resolvers.py
"""
Identity resolution (core).

Central, framework-agnostic resolver that derives a canonical identity
(namespace, kind, name) for any class. This is the **single source of truth**
for identity rules in core. Decorators should delegate to this resolver,
attach the resulting Identity to the class, register it, and emit a single
trace span using the returned metadata.

Key behaviors
-------------
- Explicit vs derived name:
  * If `name` provided via decorator arg or class attribute → preserve (trim &
    normalize separators only), **no token stripping**.
  * Otherwise derive from class name and perform **segment-aware** token
    stripping (case-insensitive; removes tokens at prefix, middle, suffix),
    then normalize.
- Namespace/kind precedence:
  * namespace: decorator arg → class attribute → module root → "default"
  * kind:      decorator arg → class attribute → "default"
- Token sources (core):
  * DEFAULT_IDENTITY_STRIP_TOKENS (core constant)
  * SIMCORE_IDENTITY_STRIP_TOKENS (env; comma/space-delimited)
  (Framework layers may extend this with additional sources.)
- Meta for tracing (flat keys):
  * ai.tuple3.raw, ai.tuple3.post_strip, ai.tuple3.post_norm
  * ai.identity.name.explicit (bool)
  * ai.identity.source.name|namespace|kind = "arg"|"attr"|"derived"
  * ai.strip_tokens (CSV), ai.strip_tokens_list (list)

This module must not import any decorator or registry code to avoid cycles.
"""


import re
from dataclasses import dataclass
from typing import Iterable, Optional, Any, TypeVar

from . import registry_resolvers as _rr
from .identity import Identity, IdentityLike
from .utils import snake, module_root, get_effective_strip_tokens
from ..types.protocols import RegistryProtocol

__all__ = [
    "IdentityResolver",
    "NameResolution",
    "resolve_identity",
    "Resolve",
]


# ------------------------- helpers (pure) -------------------------

def _is_nonempty_str(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _split_camel_and_separators(name: str) -> list[str]:
    """Split a class name into segments by CamelCase boundaries and `_`/`-`.

    Example: "CodecStrippedResponse" → ["Codec", "Stripped", "Response"]
             "Special_Response-Custom" → ["Special", "Response", "Custom"]
    """
    if not name:
        return []
    # Insert spaces before CamelCase transitions, then split on non-alnum boundaries
    s = re.sub(r"(?<=[0-9a-z])([A-Z])", r" \1", name)
    s = re.sub(r"[\-_]+", " ", s)
    parts = [p for p in re.split(r"\W+", s) if p]
    return parts


def _segment_strip_tokens(name: str, tokens: Iterable[str]) -> str:
    """Remove any full-segment matches of `tokens` (case-insensitive) from `name`.

    - Works across prefix, middle, and suffix positions (segment-aware).
    - Matching is case-insensitive on a per-segment basis.
    - Returns the remaining segments joined by '-' (normalization will finalize).
    """
    segs = _split_camel_and_separators(name)
    if not segs:
        return name

    token_ci = {t.casefold() for t in (tokens or []) if isinstance(t, str) and t}
    if not token_ci:
        return "-".join(segs)

    kept: list[str] = [s for s in segs if s.casefold() not in token_ci]
    return "-".join(kept) if kept else ""


def _normalize_name(name: str, *, lower: bool = True) -> str:
    """Collapse separators to single '-', trim edges, optionally lowercase."""
    if name is None:
        return ""
    s = re.sub(r"[._\s\-]+", "-", str(name).strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s.lower() if lower else s


def _validate_parts(namespace: str, kind: str, name: str) -> None:
    """Basic safety validation for identity parts.

    - non-empty strings
    - max length 128
    - allowed chars: A–Z, a–z, 0–9, '.', '_', '-'
    """
    allowed_re = re.compile(r"^[A-Za-z0-9._-]+$")
    for label, value in (("namespace", namespace), ("kind", kind), ("name", name)):
        if not isinstance(value, str):
            raise TypeError(f"{label} must be a string (got {type(value)!r})")
        v = value.strip()
        if not v:
            raise ValueError(f"{label} cannot be empty")
        if len(v) > 128:
            raise ValueError(f"{label} too long (>128)")
        if not allowed_re.match(v):
            raise ValueError(f"{label} contains illegal characters: {value!r}")


# ------------------------- resolver -------------------------

@dataclass
class NameResolution:
    value: str
    explicit: bool
    source: str  # "arg" | "attr" | "derived"
    raw: str
    post_strip: str


class IdentityResolver:
    """Core resolver for (namespace, kind, name).

    Subclass in framework layers (e.g., Django) to override token collection or
    namespace inference. This class is intentionally free of decorator/registry
    imports to keep layering clean.
    """

    # ----- public API -----
    def resolve(
            self,
            cls: type,
            *,
            namespace: Optional[str] = None,
            kind: Optional[str] = None,
            name: Optional[str] = None,
            context: Optional[dict[str, Any]] = None,
    ) -> tuple[Identity, dict[str, Any]]:
        """Resolve identity and return (Identity, meta) for tracing.

        The resolver always provides defaults; it never returns empty parts.
        Collisions are handled by registries, not by this class.
        """
        context = context or {}

        # Namespace
        ns_value, ns_source = self._resolve_namespace(
            cls, namespace, getattr(cls, "namespace", None)
        )
        ns_value = snake(ns_value or "default")

        # Kind
        kd_value, kd_source = self._resolve_kind(
            cls, kind, getattr(cls, "kind", None)
        )
        kd_value = snake(kd_value or "default")

        # Tokens (core)
        tokens = self._collect_strip_tokens(cls)
        tokens_list = sorted({t for t in tokens if t})
        tokens_csv = ",".join(tokens_list)

        # Name
        name_res = self._resolve_name(
            cls,
            name,
            getattr(cls, "name", None),
            tokens_list,
        )

        # Final identity
        ident = Identity(namespace=ns_value, kind=kd_value, name=name_res.value)

        # Build meta (full; caller may filter by trace level)
        meta: dict[str, Any] = {
            "orchestrai.tuple3.raw": f"{ns_value}.{kd_value}.{name_res.raw}",
            "orchestrai.tuple3.post_strip": f"{ns_value}.{kd_value}.{name_res.post_strip}",
            "orchestrai.tuple3.post_norm": ident.as_str,
            "orchestrai.identity.name.explicit": name_res.explicit,
            "orchestrai.identity.source.name": name_res.source,
            "orchestrai.identity.source.namespace": ns_source,
            "orchestrai.identity.source.kind": kd_source,
            "orchestrai.strip_tokens": tokens_csv,
            "orchestrai.strip_tokens_list": tokens_list,
        }

        # Validate last to keep meta available for debugging on failure
        _validate_parts(ident.namespace, ident.kind, ident.name)
        return ident, meta

    def preview(self, *args: Any, **kwargs: Any) -> tuple[Identity, dict[str, Any]]:
        """Alias of resolve; kept for semantic clarity when used in tooling/tests."""
        return self.resolve(*args, **kwargs)

    # ----- hook methods / override points -----
    def _resolve_namespace(
            self,
            cls: type,
            namespace_arg: Optional[str],
            namespace_attr: Optional[str],
    ) -> tuple[str, str]:
        """Return (value, source). Default: arg > attr > module_root > 'default'."""
        if _is_nonempty_str(namespace_arg):
            return str(namespace_arg).strip(), "arg"
        if _is_nonempty_str(namespace_attr):
            return str(namespace_attr).strip(), "attr"
        root = module_root(cls) or "default"
        return root, "derived"

    def _resolve_kind(
            self,
            cls: type,
            kind_arg: Optional[str],
            kind_attr: Optional[str],
    ) -> tuple[str, str]:
        """Return (value, source). Default: arg > attr > 'default'."""
        if _is_nonempty_str(kind_arg):
            return str(kind_arg).strip(), "arg"
        if _is_nonempty_str(kind_attr):
            return str(kind_attr).strip(), "attr"
        return "default", "derived"

    def _collect_strip_tokens(self, cls: type) -> tuple[str, ...]:
        """Collect tokens for derived-name stripping (core only).

        Sources (core):
          - DEFAULT_IDENTITY_STRIP_TOKENS (built-in constant)
          - IDENTITY_STRIP_TOKENS from orchestrai settings (OrchestraiSettings)

        Framework layers (e.g. Django) may extend this by passing extra tokens
        down into the underlying strip helper.
        """
        # Delegate to the core helper, which merges:
        #   - DEFAULT_IDENTITY_STRIP_TOKENS (built-in)
        #   - IDENTITY_STRIP_TOKENS from OrchestraiSettings
        #   - any optional extras provided by framework layers
        return get_effective_strip_tokens()

    def _resolve_name(
            self,
            cls: type,
            name_arg: Optional[str],
            name_attr: Optional[str],
            tokens: Iterable[str],
    ) -> NameResolution:
        # Explicit?
        if _is_nonempty_str(name_arg):
            raw = str(name_arg).strip()
            norm = _normalize_name(raw, lower=False)  # preserve case for explicit
            return NameResolution(value=norm, explicit=True, source="arg", raw=raw, post_strip=norm)
        if _is_nonempty_str(name_attr):
            raw = str(name_attr).strip()
            norm = _normalize_name(raw, lower=False)
            return NameResolution(value=norm, explicit=True, source="attr", raw=raw, post_strip=norm)

        # Derived from class name
        cls_name = getattr(cls, "__name__", "") or "default"
        raw = cls_name
        stripped = _segment_strip_tokens(raw, tokens)
        if not stripped:
            # Guard: if everything was stripped, fallback to the normalized class name
            stripped = raw
        # Normalize (derived names lowercased by convention)
        norm = _normalize_name(stripped, lower=True)
        if not norm:
            # Final guard: ensure non-empty
            norm = _normalize_name(raw, lower=True) or "default"
        return NameResolution(value=norm, explicit=False, source="derived", raw=raw, post_strip=stripped)


# ------------------------- convenience -------------------------

def resolve_identity(
        cls: type,
        *,
        resolver: Optional[IdentityResolver] = None,
        namespace: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
) -> tuple[Identity, dict[str, Any]]:
    """Public helper to resolve identity using a provided or default resolver."""
    r = resolver or IdentityResolver()
    return r.resolve(cls, namespace=namespace, kind=kind, name=name, context=context)


# ------------------------- facade (ergonomic sugar) -------------------------

T = TypeVar("T")


class Resolve:
    """Namespaced helpers exposed at Identity.resolve.

    This facade delegates to registry_resolvers to avoid import cycles.
    """

    @staticmethod
    def for_(
            component: type[T],
            identity: IdentityLike,
            *,
            __from: RegistryProtocol | None = None,
    ) -> T:
        """Strict resolver: resolve a registered component by identity.

          Returns the resolved component or raises if not found.
          """
        return _rr.for_(component, identity, __from=__from)

    @staticmethod
    def try_for_(
            component: type[T],
            identity: IdentityLike,
            *,
            __from: RegistryProtocol | None = None,
    ) -> T | None:
        """Safe resolver: never raises on lookup failure; returns None instead."""
        return _rr.try_for_(component, identity, __from=__from)

    @staticmethod
    def as_tuple3(ident: IdentityLike) -> tuple[str, str, str]:
        """Return (namespace, kind, name) for any `IdentityLike`."""
        return _rr.tuple3(ident)

    @staticmethod
    def as_label(ident: IdentityLike) -> str:
        """Return 'namespace.kind.name' for any `IdentityLike`."""
        return _rr.label(ident)

    @staticmethod
    def label_from_component(comp: Any) -> str:
        """Return the canonical label for a component that exposes `.identity`."""
        return getattr(comp, "identity").as_str
