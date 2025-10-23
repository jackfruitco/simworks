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