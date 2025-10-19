# tests/simcore_ai/identity/test_identity_parse_edgecases.py
import pytest
from simcore_ai.identity import parse_dot_identity, snake

@pytest.mark.parametrize("raw", [
    " a . b . c ",
    "A. b .C",
])
def test_parse_dot_identity_whitespace_and_case(raw):
    o, b, n = parse_dot_identity(raw)
    assert o == snake(o) and b == snake(b) and n == snake(n)
    assert (o, b, n) == ("a", "b", "c")

@pytest.mark.parametrize("raw", [
    "A..C",
    "..c",
    "a..",
])
def test_parse_dot_identity_missing_parts_raises(raw):
    with pytest.raises(Exception):
        parse_dot_identity(raw)