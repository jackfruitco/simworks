# tests/types/test_dtos_usage.py

from simcore_ai.types import UsageContent


def test_usage_content_defaults():
    u = UsageContent()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.prompt_tokens == 0
    assert u.total_tokens == 0


def test_usage_content_allows_extra_fields():
    u = UsageContent(input_tokens=10, foo=123)  # extra field
    assert u.input_tokens == 10
    # an extra field is stored due to extra="allow"
    assert getattr(u, "foo") == 123
