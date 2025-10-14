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
    - "ns.bucket.name"  -> returns ("ns", "bucket:name")
    - "ns:bucket:name"  -> returns ("ns", "bucket:name")
    - "ns|bucket|name"  -> returns ("ns", "bucket:name")   # lenient

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

    # We expect 3 segments: ns, bucket, name
    if len(parts) != 3:
        return None, None

    ns = (parts[0] or "").strip().lower()
    bucket = (parts[1] or "").strip().lower()
    name = (parts[2] or "").strip().lower()
    if not ns or not bucket or not name:
        return None, None

    return ns, f"{bucket}:{name}"
