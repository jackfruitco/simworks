# tests/simcore_ai/identity/test_identity_core.py
from __future__ import annotations

import os
import types
import pytest

from simcore_ai.identity import (
    DEFAULT_STRIP_TOKENS,
    snake,
    strip_tokens,
    derive_identity_for_class,
    parse_dot_identity,
    resolve_collision,
    IdentityMixin,
)


# -----------------------------
# snake() normalization
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
def test_snake_various_cases(raw, expected):
    assert snake(raw) == expected


# -----------------------------
# strip_tokens() edge behavior
# -----------------------------

def test_strip_tokens_edges_only_leading_and_trailing():
    # Ensure our defaults include these (as discussed in design)
    for tok in {"Codec", "Service", "Prompt", "PromptSection", "Section", "Response", "Generate", "Output", "Schema"}:
        assert tok in DEFAULT_STRIP_TOKENS

    # Leading + trailing tokens removed repeatedly
    name = "GenerateInitialResponseService"
    stripped = strip_tokens(name)  # default: edges only, repeat=True
    # Remove leading "Generate" and trailing "Service" then trailing "Response" -> "Initial"
    assert stripped == "Initial"


def test_strip_tokens_keeps_middle_content():
    # "Patient" not in core defaults — also verify middle is preserved even if it were
    name = "OutpatientInitialSchema"
    stripped = strip_tokens(name)
    # Only trailing "Schema" is removed; "OutpatientInitial" remains unchanged
    assert stripped == "OutpatientInitial"


def test_strip_tokens_repeat_and_individual_edges():
    # Remove only leading
    name = "GenerateGenerateInitial"
    stripped = strip_tokens(name, strip_trailing=False)
    assert stripped == "Initial"

    # Remove only trailing
    name = "InitialResponseServiceService"
    stripped = strip_tokens(name, strip_leading=False)
    assert stripped == "Initial"

    # No stripping when both disabled
    assert strip_tokens("GenerateInitialResponse", strip_leading=False, strip_trailing=False) == "GenerateInitialResponse"


# -----------------------------
# parse_dot_identity()
# -----------------------------

@pytest.mark.parametrize(
    "s, expected",
    [
        ("chatlab.standardized_patient.initial", ("chatlab", "standardized_patient", "initial")),
        ("a.b.c", ("a", "b", "c")),
        ("One.Two.Three", ("one", "two", "three")),  # should normalize to snake/lower
        ("ONE.TWO.HTTP2", ("one", "two", "http2")),
    ],
)
def test_parse_dot_identity_valid(s, expected):
    assert parse_dot_identity(s) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "one",
        "one.two",
        "one.two.three.four",
        "one:two:three",  # colons not allowed in dot-only parser
        "one.two.",       # missing name
        ".two.three",     # missing origin
        " .. . ",         # whitespace garbage
    ],
)
def test_parse_dot_identity_invalid(bad):
    with pytest.raises(Exception):
        parse_dot_identity(bad)


# -----------------------------
# derive_identity_for_class()
# -----------------------------

def _new_class(name: str, module: str | None = None, bases: tuple[type, ...] = ()) -> type:
    """
    Create a new class with a specific __module__ without polluting globals.
    """
    module = module or "myorigin.sub.module"
    def exec_body(ns):
        ns["__module__"] = module
    return types.new_class(name, bases=bases, exec_body=exec_body)


def test_derive_identity_core_defaults_from_module_and_name_edges():
    # Class name includes tokens "Generate", "Response", "Service" → edges will be stripped to "Initial"
    C = _new_class("GeneratePatientInitialResponseService", module="chatlab.ai.services")
    o, b, n = derive_identity_for_class(C)  # no overrides
    # Core origin is module root → "chatlab"
    # bucket defaults to "default" (core)
    # name from class → "Initial" → snake → "initial"
    assert (o, b, n) == ("chatlab", "default", "initial")


def test_derive_identity_respects_overrides_and_normalizes():
    C = _new_class("Whatever")
    o, b, n = derive_identity_for_class(C, origin="ChatLab", bucket="Standardized_Patient", name="InitialResponse")
    assert (o, b, n) == ("chatlab", "standardized_patient", "initial_response")


def test_derive_identity_extra_tokens_affect_name_only():
    # Add an extra token to remove from edges
    C = _new_class("PatientInitialSchema", module="lab.app.schemas")
    o, b, n = derive_identity_for_class(C, extra_strip_tokens={"Patient"})
    assert (o, b, n) == ("lab", "default", "initial")


# -----------------------------
# resolve_collision()
# -----------------------------

def test_resolve_collision_debug_true_raises(monkeypatch):
    # Simulate DEBUG/strict mode
    monkeypatch.setenv("SIMCORE_AI_DEBUG", "1")
    existing = {("chatlab", "standardized_patient", "initial")}
    with pytest.raises(Exception):
        resolve_collision(("chatlab", "standardized_patient", "initial"), existing, debug=None)


def test_resolve_collision_debug_false_suffix(monkeypatch):
    # Simulate non-debug (production) mode
    monkeypatch.delenv("SIMCORE_AI_DEBUG", raising=False)
    existing = {("chatlab", "standardized_patient", "initial")}
    # Expect suffix -2 on the name portion
    o, b, n = resolve_collision(("chatlab", "standardized_patient", "initial"), existing, debug=None)
    assert (o, b, n) == ("chatlab", "standardized_patient", "initial-2")


def test_resolve_collision_multiple_increments(monkeypatch):
    monkeypatch.delenv("SIMCORE_AI_DEBUG", raising=False)
    existing = {
        ("chatlab", "standardized_patient", "initial"),
        ("chatlab", "standardized_patient", "initial-2"),
        ("chatlab", "standardized_patient", "initial-3"),
    }
    o, b, n = resolve_collision(("chatlab", "standardized_patient", "initial"), existing, debug=False)
    assert n == "initial-4"


# -----------------------------
# IdentityMixin
# -----------------------------

def test_identity_mixin_autoderive_core(monkeypatch):
    # Create a class that uses IdentityMixin only (core rules)
    C = _new_class("GeneratePatientInitialResponseService", module="myorigin.ai.services", bases=(IdentityMixin,))
    # identity_tuple should autoderive using core rules:
    # origin = module root "myorigin", bucket = "default",
    # name = "PatientInitial" after stripping leading "Generate" and trailing "Service" and "Response"
    o, b, n = C.identity_tuple()  # type: ignore[attr-defined]
    assert (o, b, n) == ("myorigin", "default", "patient_initial")


def test_identity_mixin_respects_explicit_attrs():
    # If a subclass sets class attrs, those should win
    class MyThing(IdentityMixin):  # type: ignore[misc]
        origin = "ChatLab"
        bucket = "Standardized_Patient"
        name = "Initial"

    assert MyThing.identity_tuple() == ("chatlab", "standardized_patient", "initial")