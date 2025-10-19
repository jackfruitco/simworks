# simcore_ai_django/codecs/registry.py
from __future__ import annotations

from typing import Dict, Iterable, Optional, Tuple, Type, Union

import warnings

from simcore_ai.codecs.exceptions import CodecNotFoundError, CodecRegistrationError
try:
    from simcore_ai.types.identity import Identity  # if available
except Exception:
    Identity = object  # type: ignore[misc,assignment]

from .base import DjangoBaseLLMCodec

# ------------------------ helpers ------------------------

def _norm(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s.lower().replace(" ", "_") if s else None


def _parse_legacy_bucket_name(name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse legacy flat name form "bucket:name" into (bucket, name).
    Returns (None, None) if it cannot be parsed.
    """
    if not name or ":" not in name:
        return None, None
    bucket, nm = name.split(":", 1)
    bucket_n = _norm(bucket)
    name_n = _norm(nm)
    if not bucket_n or not name_n:
        return None, None
    return bucket_n, name_n


def _parse_codec_identity(value: Union[str, Identity]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Accept "ns.bucket.name" or "ns:bucket:name" or an Identity and return (ns, bucket, name).
    """
    if value is None:
        return None, None, None

    # Identity object
    try:
        if hasattr(value, "origin") and hasattr(value, "bucket") and hasattr(value, "name"):
            ns = _norm(getattr(value, "origin"))
            buck = _norm(getattr(value, "bucket"))
            nm = _norm(getattr(value, "name"))
            return ns, buck, nm
    except Exception:
        pass

    # String forms
    if isinstance(value, str):
        if ":" in value:
            parts = value.split(":")
        else:
            parts = value.split(".")
        if len(parts) != 3:
            return None, None, None
        ns = _norm(parts[0])
        buck = _norm(parts[1])
        nm = _norm(parts[2])
        return ns, buck, nm

    return None, None, None

# ------------------------ registry ------------------------

class DjangoCodecRegistry:
    """
    Registry of Django codec **classes** keyed by tuple3 identity: (origin, bucket, name).

    Preferred registration:
        register("chatlab", "sim_responses", "patient_initial_response", PatientInitialResponseCodec)

    Legacy compatibility:
        register("chatlab", "sim_responses:patient_initial_response", PatientInitialResponseCodec)  # DEPRECATED
    """

    # canonical storage
    _by_tuple: Dict[Tuple[str, str, str], Type[DjangoBaseLLMCodec]] = {}

    @classmethod
    def register(cls, origin: str, bucket: str, name: str, codec_class: Type[DjangoBaseLLMCodec]) -> None:
        ns = _norm(origin) or "default"
        buck = _norm(bucket) or "default"
        nm = _norm(name) or "default"

        key = (ns, buck, nm)
        if key in cls._by_tuple:
            raise CodecRegistrationError(f"Duplicate codec for identity: {ns}.{buck}.{nm}")

        # annotate class with identity (helpful for logging)
        setattr(codec_class, "origin", ns)
        setattr(codec_class, "bucket", buck)
        setattr(codec_class, "name", nm)

        cls._by_tuple[key] = codec_class

    @classmethod
    def register_legacy(cls, origin: str, legacy_bucket_name: str, codec_class: Type[DjangoBaseLLMCodec]) -> None:
        warnings.warn(
            "Registering codecs using name='bucket:name' is deprecated; "
            "use register(origin, bucket, name, codec_class) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        buck, nm = _parse_legacy_bucket_name(legacy_bucket_name)
        if not buck or not nm:
            raise CodecRegistrationError("Malformed legacy codec name; expected 'bucket:name'")
        cls.register(origin, buck, nm, codec_class)

    @classmethod
    def get_codec(cls, origin: str, bucket: str, name: str) -> Optional[Type[DjangoBaseLLMCodec]]:
        ns = _norm(origin) or "default"
        buck = _norm(bucket) or "default"
        nm = _norm(name) or "default"

        # Exact
        obj = cls._by_tuple.get((ns, buck, nm))
        if obj:
            return obj

        # Fallbacks
        obj = cls._by_tuple.get((ns, buck, "default"))
        if obj:
            return obj
        obj = cls._by_tuple.get((ns, "default", "default"))
        if obj:
            return obj

        return None

    @classmethod
    def get_by_identity(cls, value: Union[str, Identity]) -> Optional[Type[DjangoBaseLLMCodec]]:
        ns, buck, nm = _parse_codec_identity(value)
        if ns and buck and nm:
            return cls.get_codec(ns, buck, nm)
        return None

    @classmethod
    def require(cls, origin: str, bucket: str, name: str) -> Type[DjangoBaseLLMCodec]:
        obj = cls.get_codec(origin, bucket, name)
        if obj is None:
            available = ", ".join(sorted(f"{ns}.{b}.{n}" for (ns, b, n) in cls._by_tuple.keys())) or "<none>"
            raise CodecNotFoundError(f"Codec '{origin}.{bucket}.{name}' not registered; available: {available}")
        return obj

    @classmethod
    def clear(cls) -> None:
        cls._by_tuple.clear()

    @classmethod
    def names(cls) -> Iterable[str]:
        return (f"{ns}.{b}.{n}" for (ns, b, n) in cls._by_tuple.keys())

# ------------------------ API helpers ------------------------

def register(namespace: str, bucket_or_legacy: str, name_or_class, maybe_class: Type[DjangoBaseLLMCodec] | None = None) -> None:
    """
    Flexible register that supports both modern tuple3 and legacy 'bucket:name'.

    Usage:
        register("chatlab", "sim_responses", "patient_initial_response", PatientCodec)   # preferred
        register("chatlab", "sim_responses:patient_initial_response", PatientCodec)     # deprecated
    """
    if maybe_class is None:
        # legacy form: (namespace, "bucket:name", codec_class)
        codec_class = name_or_class  # type: ignore[assignment]
        DjangoCodecRegistry.register_legacy(namespace, bucket_or_legacy, codec_class)
    else:
        DjangoCodecRegistry.register(namespace, bucket_or_legacy, name_or_class, maybe_class)  # type: ignore[arg-type]

def get_codec(namespace: str, bucket: str, name: str) -> Optional[Type[DjangoBaseLLMCodec]]:
    return DjangoCodecRegistry.get_codec(namespace, bucket, name)

def get_by_identity(value: Union[str, Identity]) -> Optional[Type[DjangoBaseLLMCodec]]:
    return DjangoCodecRegistry.get_by_identity(value)
