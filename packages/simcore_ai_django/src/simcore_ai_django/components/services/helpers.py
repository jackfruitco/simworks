# simcore_ai_django/services/helpers.py
"""Helpers for identity parsing and light formatting in Django services.

This module intentionally **does not perform identity derivation** (token stripping,
fallbacks, etc.). Derivation rules live in the IdentityResolver classes.

What we do here:
- Parse codec/service identity strings using the centralized Identity helpers
  from `simcore_ai.identity` (single source of truth).
- Offer a small convenience to interpret a `codec_name` hint into (kind, name).

Notes
-----
• Strict dot-only identities are preferred ("namespace.kind.name").
• All output are normalized to lowercase for consistency in logs/metrics.
"""



# Centralized identity primitives/utilities
from simcore_ai.identity import coerce_identity_key


__all__ = [
    "_parse_codec_identity",
    "_kind_name_from_codec_name",
]


def _parse_codec_identity(codec_identity: str) -> tuple[str | None, str | None, str | None]:
    """Strictly parse a codec identity into (namespace, kind, name).

    Expected forms
    --------------
    • "namespace.kind.name"     (preferred; dot-only)

    Behavior
    --------
    • Returns a lowercased (ns, kind, name) tuple on success.
    • Returns (None, None, None) if parsing/validation fails.
    • Delegates to the centralized `coerce_identity_key(...)` so parsing rules
      stay consistent across the codebase.

    This does **not** derive missing parts; it only parses/validates.
    """
    if not isinstance(codec_identity, str) or not codec_identity.strip():
        return None, None, None

    key = coerce_identity_key(codec_identity)
    if key is None:
        return None, None, None

    ns, kd, nm = key
    return ns.lower(), kd.lower(), nm.lower()


def _kind_name_from_codec_name(
    codec_name: str | None,
    fallback_kind: str | None,
    fallback_name: str | None,
) -> tuple[str | None, str | None]:
    """Interpret an optional `codec_name` hint into (kind, name).

    Supported forms
    ---------------
    • None          -> (fallback_kind, fallback_name)
    • "default"     -> ("default", "default")
    • "kind.name"   -> ("kind", "name")

    Returns lowercased kind/name when parsed; otherwise returns the fallbacks.

    Notes
    -----
    • This helper is intentionally narrow in scope; it does not support
      "namespace.kind.name" (that’s a full identity and should be passed
      through `_parse_codec_identity` / Identity utilities instead).
    """
    if not codec_name:
        return fallback_kind, fallback_name

    raw = str(codec_name).strip()
    if raw == "default":
        return "default", "default"

    parts = [p for p in raw.split(".") if p]
    if len(parts) == 2:
        return parts[0].lower(), parts[1].lower()

    return fallback_kind, fallback_name