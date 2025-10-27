"""Helper functions for codec identity parsing and namespace inference.

This module enforces a strict dot-only identity policy for codec identities and
normalizes parsed parts to lowercase.

Notes
-----
- Identity *derivation* (token stripping, inference) is handled by the
  IdentityResolver in `simcore_ai.identity.resolution`. These helpers only
  parse/format values and never perform derivation.
"""

from __future__ import annotations

from typing import Tuple

from django.apps import apps

from simcore_ai.identity.utils import parse_dot_identity


def _infer_namespace_from_module(module_name: str) -> str:
    """Returns the Django app label for a given module name when possible,
    otherwise falls back to the first module segment. The result is lowercased.
    """
    for app in apps.get_app_configs():
        if module_name.startswith(app.name):
            return app.label.lower()
    return module_name.split(".")[0].lower()


def _parse_codec_identity(codec_identity: str) -> Tuple[str | None, str | None, str | None]:
    """
    Strictly parse a dot-only codec identity into (namespace, kind, name).

    Accepted format:
    - "ns.kind.name"  -> returns ("ns", "kind", "name")

    Behavior:
    - Returns all-lowercase parts on success.
    - Returns (None, None, None) if it cannot parse.
    - Delegates to core `parse_dot_identity` to prevent drift.
    """
    if not isinstance(codec_identity, str) or not codec_identity.strip():
        return None, None, None
    try:
        ns, kd, nm = parse_dot_identity(codec_identity)
        return ns.lower(), kd.lower(), nm.lower()
    except Exception:
        return None, None, None


def _kind_name_from_codec_name(
        codec_name: str | None,
        fallback_kind: str | None,
        fallback_name: str | None,
) -> tuple[str | None, str | None]:
    """Interpret an optional codec_name into (kind, name).

    Supported forms:
      - None -> (fallback_kind, fallback_name)
      - "default" -> ("default", "default")
      - "kind.name" -> ("kind", "name")

    Returns lowercased kind/name when parsed; preserves fallbacks if malformed.
    """
    if not codec_name:
        return fallback_kind, fallback_name
    raw = str(codec_name).strip()
    if raw == "default":
        return "default", "default"
    parts = [p.strip() for p in raw.split(".") if p.strip()]
    if len(parts) == 2:
        return parts[0].lower(), parts[1].lower()
    return fallback_kind, fallback_name
