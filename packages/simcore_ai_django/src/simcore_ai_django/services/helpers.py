from __future__ import annotations

from typing import Tuple

from django.apps import apps


def _infer_namespace_from_module(module_name: str) -> str:
    for app in apps.get_app_configs():
        if module_name.startswith(app.name):
            return app.label.lower()
    return module_name.split(".")[0].lower()


def _parse_codec_identity(codec_identity: str) -> Tuple[str | None, str | None]:
    """
    Parse a codec identity into (namespace, codec_name).

    Accepted formats:
    - "ns.kind.name"  -> returns ("ns", "kind:name")
    - "ns:kind:name"  -> returns ("ns", "kind:name")
    - "ns|kind|name"  -> returns ("ns", "kind:name")   # lenient

    Returns (None, None) if it cannot parse.
    """
    if not codec_identity or not isinstance(codec_identity, str):
        return None, None
    # Try delimiter variants
    if ":" in codec_identity:
        parts = codec_identity.split(":")
    elif "." in codec_identity:
        parts = codec_identity.split(".")
    elif "|" in codec_identity:
        parts = codec_identity.split("|")
    else:
        return None, None

    # We expect 3 segments: ns, kind, name
    if len(parts) != 3:
        return None, None

    ns = (parts[0] or "").strip().lower()
    kind = (parts[1] or "").strip().lower()
    name = (parts[2] or "").strip().lower()
    if not ns or not kind or not name:
        return None, None

    return ns, f"{kind}:{name}"


def _kind_name_from_codec_name(codec_name: str | None, fallback_kind: str | None, fallback_name: str | None) -> tuple[str | None, str | None]:
    """Interpret an optional codec_name into (kind, name).
    Supported forms:
      - None -> (fallback_kind, fallback_name)
      - "default" -> ("default", "default")
      - "kind.name" -> ("kind", "name")
      - Any legacy "kind:name" will be treated as "kind.name" (no warnings).
    """
    if not codec_name:
        return fallback_kind, fallback_name
    raw = str(codec_name).strip()
    raw = raw.replace(":", ".")  # tolerate legacy, but do not emit warnings
    if raw == "default":
        return "default", "default"
    parts = [p.strip() for p in raw.split(".") if p.strip()]
    if len(parts) == 2:
        return parts[0], parts[1]
    # Fallback: keep provided fallback if malformed
    return fallback_kind, fallback_name
