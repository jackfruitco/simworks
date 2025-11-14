# tests/simcore_ai/identity/test_identity_core.py
from __future__ import annotations

import types
import pytest

from simcore_ai.identity import Identity
from simcore_ai.decorators.helpers import (
    derive_name,
    derive_namespace_core,
    derive_kind,
    strip_name_tokens,
    normalize_name,
    validate_identity,
)
from simcore_ai.codecs.decorators import codec  # core decorator (no registry)


# -----------------------------
# normalize_name() / derive_name() normalization
# -----------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Initial", "initial"),
        ("PatientInitial", "patient_initial"),
        ("GenerateInitialResponse", "generate_initial_response"),
        ("ChatLABHTTP2Codec", "chat_lab_http2_codec"),
        ("already_snake_case", "already_snake_case"),
        ("kebab-case-name", "kebab_case_name"),
        ("Mixed_SnakeCamelHTTP", "mixed_snake_camel_http"),
        ("", ""),
    ],
)
def test_normalize_and_derive_name_various_cases(raw, expected):
    # derive_name from a synthetic class when not provided falls back to class name,
    # but here we directly normalize explicit strings to keep the old coverage.
    assert normalize_name(raw) == expected


# -----------------------------
# derive_name() explicit and fallback behavior
# -----------------------------

def test_derive_name_from_class_and_explicit_value():
    class ExampleClass:
        pass

    # When explicit name is provided, derive_name should return it as-is (no normalization here).
    assert derive_name(ExampleClass, name_arg="CustomName", name_attr=None, derived_lower=True) == "CustomName"

    # When name is not provided, derive_name should fall back to the class name.
    # With derived_lower=True, it should lowercase the raw class name (normalization happens later).
    assert derive_name(ExampleClass, name_arg=None, name_attr=None, derived_lower=True) == "exampleclass"

    # When an empty string is provided, treat it as not provided and fall back to the class name.
    assert derive_name(ExampleClass, name_arg="", name_attr=None, derived_lower=True) == "exampleclass"


# -----------------------------
# strip_name_tokens() edge behavior (name-only)
# -----------------------------

def test_strip_name_tokens_edges_only_leading_and_trailing():
    # Leading + trailing tokens removed repeatedly (case-insensitive)
    name = "GenerateInitialResponseService"
    stripped = strip_name_tokens(name, tokens=("Generate", "Service", "Response"))
    # Remove leading "Generate" and trailing "Service" then trailing "Response" -> "Initial"
    assert stripped == "Initial"


def test_strip_name_tokens_keeps_middle_content():
    # Only trailing token is removed; middle content remains
    name = "OutpatientInitialSchema"
    stripped = strip_name_tokens(name, tokens=("Schema",))
    assert stripped == "OutpatientInitial"


def test_strip_name_tokens_repeat_and_individual_edges():
    # Remove only leading (simulate by passing tokens but pre-trim trailing first)
    name = "GenerateGenerateInitial"
    stripped = strip_name_tokens(name, tokens=("Generate",))
    assert stripped == "Initial"

    # Remove only trailing chain
    name = "InitialResponseServiceService"
    stripped = strip_name_tokens(name, tokens=("Response", "Service"))
    assert stripped == "Initial"

    # No stripping when tokens do not match edges
    assert strip_name_tokens("GenerateInitialResponse", tokens=("Foo",)) == "GenerateInitialResponse"


# -----------------------------
# derive_namespace_core / derive_kind
# -----------------------------

def _new_class(name: str, module: str | None = None, bases: tuple[type, ...] = ()) -> type:
    module = module or "myorigin.sub.module"
    def exec_body(ns):
        ns["__module__"] = module
    return types.new_class(name, bases=bases, exec_body=exec_body)


def test_derive_namespace_core_from_module_and_attrs():
    C1 = _new_class("Whatever", module="chatlab.ai.services")
    ns = derive_namespace_core(C1, namespace_arg=None, namespace_attr=None)
    assert ns == "chatlab"

    C2 = _new_class("Whatever", module="x.y")
    ns = derive_namespace_core(C2, namespace_arg="AppNS", namespace_attr=None)
    assert ns == "AppNS"

    class Base:
        namespace = "FromAttr"
    C3 = _new_class("Whatever", module="z.t", bases=(Base,))
    ns = derive_namespace_core(C3, namespace_arg=None, namespace_attr=getattr(C3, "namespace", None))
    assert ns == "FromAttr"


def test_derive_kind_default_and_overrides():
    C = _new_class("Whatever")
    assert derive_kind(C, kind_arg=None, kind_attr=None, default="codec") == "codec"
    class WithKind:
        kind = "service"
    C2 = _new_class("Whatever", bases=(WithKind,))
    assert derive_kind(C2, kind_arg=None, kind_attr=getattr(C2, "kind", None), default="codec") == "service"
    assert derive_kind(C2, kind_arg="schema", kind_attr=None, default="codec") == "schema"


# -----------------------------
# validate_identity()
# -----------------------------

@pytest.mark.parametrize(
    "ns,kd,nm",
    [
        ("chatlab", "codec", "initial"),
        ("a", "b", "c"),
        ("one", "two", "http2"),
    ],
)
def test_validate_identity_success(ns, kd, nm):
    # Should not raise
    validate_identity(ns, kd, nm)
    Identity(namespace=ns, kind=kd, name=nm)


@pytest.mark.parametrize(
    "ns,kd,nm",
    [
        ("", "codec", "x"),
        ("ns", "", "x"),
        ("ns", "k", ""),
        ("bad space", "codec", "x"),
    ],
)
def test_validate_identity_fail(ns, kd, nm):
    with pytest.raises(Exception):
        validate_identity(ns, kd, nm)


# -----------------------------
# Core decorator attaches identity (no registration)
# -----------------------------

def test_core_codec_decorator_attaches_identity_without_registration():
    @codec
    class GeneratePatientInitialResponseService:
        __module__ = "chatlab.ai.services"
        # no explicit namespace/kind/name provided
        pass

    # Core decorator uses no strip tokens → name is derived from class directly and normalized
    cls = GeneratePatientInitialResponseService
    assert hasattr(cls, "identity_obj") and hasattr(cls, "identity")
    ns, kd, nm = cls.identity
    assert ns == "chatlab"  # module root
    assert kd == "codec"     # domain default set in core codec decorator
    # full normalized class name, no token stripping at core layer
    assert nm == "generate_patient_initial_response_service"


# tests/simcore_ai/identity/test_identity_parse_edgecases.py
import pytest
from simcore_ai.decorators.helpers import normalize_name, validate_identity


@pytest.mark.parametrize("raw", [
    " a . b . c ",
    "A. b .C",
])
def test_normalize_name_whitespace_and_case(raw):
    # We no longer parse dot-joined identities in core; instead we validate parts
    a, b, c = [normalize_name(p.strip()) for p in raw.split(".")]
    assert (a, b, c) == ("a", "b", "c")
    validate_identity(a, b, c)  # should not raise


@pytest.mark.parametrize("bad_parts", [
    ("A", "", "C"),
    ("", "b", "c"),
    ("a b", "c", "d"),
])
def test_validate_identity_missing_or_illegal_raises(bad_parts):
    a, b, c = bad_parts
    with pytest.raises(Exception):
        validate_identity(a, b, c)