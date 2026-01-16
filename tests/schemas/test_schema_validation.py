# tests/schemas/test_schema_validation.py
"""
Validation behavior tests for Result* types.

Tests that Result* types correctly validate:
- Required fields
- Literal discriminators
- Discriminated unions
- Extra field rejection (strict mode)
"""

import pytest
from pydantic import ValidationError
from orchestrai.types import (
    ResultMessageItem,
    ResultTextContent,
    ResultImageContent,
    ResultToolCallContent,
    ResultToolResultContent,
    ResultMetafield,
    ContentRole,
)


class TestResultContentValidation:
    """Tests for Result* content type validation."""

    def test_result_text_content_requires_type(self):
        """ResultTextContent requires type field."""
        with pytest.raises(ValidationError) as exc_info:
            ResultTextContent(text="Hello")  # Missing type!

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("type",) for e in errors), "type field must be required"

    def test_result_text_content_requires_text(self):
        """ResultTextContent requires text field."""
        with pytest.raises(ValidationError) as exc_info:
            ResultTextContent(type="text")  # Missing text!

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("text",) for e in errors), "text field must be required"

    def test_result_text_content_validates_with_all_fields(self):
        """ResultTextContent validates when all fields provided."""
        content = ResultTextContent(type="text", text="Hello")
        assert content.type == "text"
        assert content.text == "Hello"

    def test_result_text_content_rejects_extra_fields(self):
        """ResultTextContent rejects extra fields (strict mode)."""
        with pytest.raises(ValidationError) as exc_info:
            ResultTextContent(type="text", text="Hello", extra_field="not_allowed")

        errors = exc_info.value.errors()
        assert any("extra_field" in str(e) for e in errors), "Extra fields must be rejected"

    def test_result_image_content_requires_all_fields(self):
        """ResultImageContent requires all fields."""
        # Missing mime_type
        with pytest.raises(ValidationError):
            ResultImageContent(type="image", data_b64="xyz")

        # Missing data_b64
        with pytest.raises(ValidationError):
            ResultImageContent(type="image", mime_type="image/png")

        # All fields provided - should work
        content = ResultImageContent(
            type="image",
            mime_type="image/png",
            data_b64="base64data"
        )
        assert content.mime_type == "image/png"


class TestResultMessageValidation:
    """Tests for ResultMessageItem validation."""

    def test_result_message_requires_role(self):
        """ResultMessageItem requires role."""
        with pytest.raises(ValidationError) as exc_info:
            ResultMessageItem(
                content=[ResultTextContent(type="text", text="Hi")],
                item_meta=[]
            )

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("role",) for e in errors)

    def test_result_message_requires_content(self):
        """ResultMessageItem requires content."""
        with pytest.raises(ValidationError) as exc_info:
            ResultMessageItem(
                role=ContentRole.ASSISTANT,
                item_meta=[]
            )

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("content",) for e in errors)

    def test_result_message_requires_item_meta(self):
        """ResultMessageItem requires item_meta (even if empty)."""
        with pytest.raises(ValidationError) as exc_info:
            ResultMessageItem(
                role=ContentRole.ASSISTANT,
                content=[ResultTextContent(type="text", text="Hi")]
            )

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("item_meta",) for e in errors)

    def test_result_message_validates_with_all_fields(self):
        """ResultMessageItem validates when all fields provided."""
        msg = ResultMessageItem(
            role=ContentRole.ASSISTANT,
            content=[ResultTextContent(type="text", text="Hello")],
            item_meta=[]
        )
        assert msg.role == ContentRole.ASSISTANT
        assert len(msg.content) == 1
        assert msg.item_meta == []

    def test_result_message_rejects_extra_fields(self):
        """ResultMessageItem rejects extra fields."""
        with pytest.raises(ValidationError):
            ResultMessageItem(
                role=ContentRole.ASSISTANT,
                content=[ResultTextContent(type="text", text="Hi")],
                item_meta=[],
                extra="not_allowed"
            )


class TestLiteralDiscriminatorValidation:
    """Tests for literal discriminator validation."""

    def test_wrong_literal_fails(self):
        """Providing wrong literal value fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ResultTextContent(type="wrong_type", text="Hello")

        errors = exc_info.value.errors()
        # Should fail on literal validation
        assert any(e["loc"] == ("type",) for e in errors)

    def test_correct_literal_validates(self):
        """Providing correct literal value validates."""
        content = ResultTextContent(type="text", text="Hello")
        assert content.type == "text"


class TestDiscriminatedUnionValidation:
    """Tests for discriminated union validation in content array."""

    def test_content_union_accepts_text(self):
        """Content union accepts ResultTextContent."""
        msg = ResultMessageItem(
            role=ContentRole.ASSISTANT,
            content=[ResultTextContent(type="text", text="Hello")],
            item_meta=[]
        )
        assert isinstance(msg.content[0], ResultTextContent)

    def test_content_union_accepts_image(self):
        """Content union accepts ResultImageContent."""
        msg = ResultMessageItem(
            role=ContentRole.ASSISTANT,
            content=[
                ResultImageContent(
                    type="image",
                    mime_type="image/png",
                    data_b64="data"
                )
            ],
            item_meta=[]
        )
        assert isinstance(msg.content[0], ResultImageContent)

    def test_content_union_accepts_mixed(self):
        """Content union accepts mixed content types."""
        msg = ResultMessageItem(
            role=ContentRole.ASSISTANT,
            content=[
                ResultTextContent(type="text", text="Hello"),
                ResultImageContent(type="image", mime_type="image/png", data_b64="data"),
            ],
            item_meta=[]
        )
        assert len(msg.content) == 2
        assert isinstance(msg.content[0], ResultTextContent)
        assert isinstance(msg.content[1], ResultImageContent)


class TestNullableFieldValidation:
    """Tests for nullable field validation."""

    def test_tool_result_nullable_fields_require_explicit_none(self):
        """ResultToolResultContent nullable fields must be explicitly provided."""
        # All nullable fields omitted - should fail
        with pytest.raises(ValidationError):
            ResultToolResultContent(
                type="tool_result",
                call_id="123"
            )

        # All fields provided (even None) - should work
        result = ResultToolResultContent(
            type="tool_result",
            call_id="123",
            result_text=None,
            result_json_str=None,
            mime_type=None,
            data_b64=None
        )
        assert result.result_text is None
        assert result.mime_type is None

    def test_tool_result_accepts_actual_values(self):
        """ResultToolResultContent accepts actual values for nullable fields."""
        result = ResultToolResultContent(
            type="tool_result",
            call_id="123",
            result_text="Success",
            result_json_str=None,
            mime_type="text/plain",
            data_b64=None
        )
        assert result.result_text == "Success"
        assert result.mime_type == "text/plain"


class TestMetafieldValidation:
    """Tests for ResultMetafield validation."""

    def test_metafield_requires_key_and_value(self):
        """ResultMetafield requires both key and value."""
        # Missing value
        with pytest.raises(ValidationError):
            ResultMetafield(key="test")

        # Missing key
        with pytest.raises(ValidationError):
            ResultMetafield(value="test")

        # Both provided - should work
        field = ResultMetafield(key="test", value="123")
        assert field.key == "test"
        assert field.value == "123"

    def test_metafield_accepts_primitive_types(self):
        """ResultMetafield accepts string, int, float, bool, None."""
        # String
        ResultMetafield(key="k1", value="string")

        # Int
        ResultMetafield(key="k2", value=42)

        # Float
        ResultMetafield(key="k3", value=3.14)

        # Bool
        ResultMetafield(key="k4", value=True)

        # None
        ResultMetafield(key="k5", value=None)

    def test_metafield_rejects_complex_types(self):
        """ResultMetafield rejects complex types (dict, list)."""
        with pytest.raises(ValidationError):
            ResultMetafield(key="test", value={"nested": "object"})

        with pytest.raises(ValidationError):
            ResultMetafield(key="test", value=["array", "values"])
