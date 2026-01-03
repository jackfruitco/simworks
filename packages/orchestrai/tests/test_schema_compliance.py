"""
Comprehensive tests for OpenAI Structured Outputs schema compliance.

Tests cover:
- Metafield validation and usage
- Schema lint utility (100% branch coverage)
- Integration with schema decorator
- Real schema compliance checks
"""

import pytest
from pydantic import BaseModel, Field, ValidationError

from orchestrai.types import Metafield, HasItemMeta, OutputItem, ContentRole, OutputTextContent
from orchestrai.schema_lint import (
    lint_schema,
    format_violations,
    validate_pydantic_schema,
    SchemaViolation,
)


class TestMetafield:
    """Tests for Metafield type."""

    def test_metafield_valid_string_value(self):
        """Metafield accepts string values."""
        mf = Metafield(key="type", value="diagnosis")
        assert mf.key == "type"
        assert mf.value == "diagnosis"

    def test_metafield_valid_int_value(self):
        """Metafield accepts int values."""
        mf = Metafield(key="score", value=95)
        assert mf.key == "score"
        assert mf.value == 95

    def test_metafield_valid_float_value(self):
        """Metafield accepts float values."""
        mf = Metafield(key="confidence", value=0.95)
        assert mf.key == "confidence"
        assert mf.value == 0.95

    def test_metafield_valid_bool_value(self):
        """Metafield accepts bool values."""
        mf = Metafield(key="verified", value=True)
        assert mf.key == "verified"
        assert mf.value is True

    def test_metafield_valid_none_value(self):
        """Metafield accepts None values."""
        mf = Metafield(key="optional", value=None)
        assert mf.key == "optional"
        assert mf.value is None

    def test_metafield_rejects_empty_key(self):
        """Metafield rejects empty string keys."""
        with pytest.raises(ValidationError) as exc_info:
            Metafield(key="", value="test")
        assert "min_length" in str(exc_info.value).lower() or "string_too_short" in str(exc_info.value).lower()

    def test_metafield_rejects_dict_value(self):
        """Metafield rejects dict values (must use primitives only)."""
        with pytest.raises(ValidationError):
            Metafield(key="nested", value={"foo": "bar"})

    def test_metafield_rejects_list_value(self):
        """Metafield rejects list values (must use primitives only)."""
        with pytest.raises(ValidationError):
            Metafield(key="items", value=["a", "b"])

    def test_metafield_schema_is_strict(self):
        """Metafield schema has additionalProperties: false."""
        schema = Metafield.model_json_schema()
        assert schema["additionalProperties"] is False

    def test_metafield_schema_has_required(self):
        """Metafield schema has complete required list."""
        schema = Metafield.model_json_schema()
        assert set(schema["required"]) == {"key", "value"}

    def test_metafield_in_list_default_empty(self):
        """Metafield list defaults to empty."""
        class TestSchema(BaseModel):
            meta: list[Metafield] = Field(default_factory=list)

        obj = TestSchema()
        assert obj.meta == []

    def test_metafield_in_list_accepts_multiple(self):
        """Metafield list accepts multiple entries."""
        class TestSchema(BaseModel):
            meta: list[Metafield] = Field(default_factory=list)

        obj = TestSchema(meta=[
            Metafield(key="a", value=1),
            Metafield(key="b", value="test"),
        ])
        assert len(obj.meta) == 2
        assert obj.meta[0].key == "a"
        assert obj.meta[1].value == "test"


class TestHasItemMeta:
    """Tests for HasItemMeta mixin."""

    def test_has_item_meta_provides_field(self):
        """HasItemMeta mixin provides item_meta field."""
        class TestModel(HasItemMeta, BaseModel):
            name: str

        obj = TestModel(name="test")
        assert hasattr(obj, "item_meta")
        assert obj.item_meta == []

    def test_has_item_meta_accepts_values(self):
        """HasItemMeta accepts metadata values."""
        class TestModel(HasItemMeta, BaseModel):
            name: str

        obj = TestModel(
            name="test",
            item_meta=[Metafield(key="type", value="example")]
        )
        assert len(obj.item_meta) == 1
        assert obj.item_meta[0].key == "type"


class TestOutputItemMigration:
    """Tests for OutputItem.item_meta migration to Metafield."""

    def test_output_item_has_metafield_list(self):
        """OutputItem.item_meta is list[Metafield]."""
        output = OutputItem(
            role=ContentRole.ASSISTANT,
            content=[OutputTextContent(text="Hello")],
            item_meta=[]
        )
        assert output.item_meta == []

    def test_output_item_accepts_metadata(self):
        """OutputItem accepts metadata as Metafield list."""
        output = OutputItem(
            role=ContentRole.ASSISTANT,
            content=[OutputTextContent(text="Hello")],
            item_meta=[
                Metafield(key="source", value="llm"),
                Metafield(key="tokens", value=100),
            ]
        )
        assert len(output.item_meta) == 2
        assert output.item_meta[0].key == "source"

    def test_output_item_schema_compliant(self):
        """OutputItem schema is OpenAI strict mode compliant."""
        schema = OutputItem.model_json_schema()
        violations = lint_schema(schema)
        assert violations == [], f"Schema has violations: {format_violations(violations)}"


class TestSchemaLint:
    """Tests for schema_lint utility (100% branch coverage)."""

    def test_lint_compliant_schema_returns_empty(self):
        """Lint returns empty list for compliant schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"],
            "additionalProperties": False
        }
        violations = lint_schema(schema)
        assert violations == []

    def test_lint_detects_missing_additional_properties(self):
        """Lint detects missing additionalProperties."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
            # Missing additionalProperties
        }
        violations = lint_schema(schema)
        assert len(violations) == 1
        assert violations[0].rule == "additionalProperties_missing"
        assert "additionalProperties" in violations[0].message

    def test_lint_detects_additional_properties_true(self):
        """Lint detects additionalProperties: true."""
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": True
        }
        violations = lint_schema(schema)
        assert any(v.rule == "additionalProperties_true" for v in violations)

    def test_lint_detects_additional_properties_schema(self):
        """Lint detects additionalProperties as schema (open map)."""
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": {"type": "string"}
        }
        violations = lint_schema(schema)
        assert any(v.rule == "additionalProperties_open_map" for v in violations)

    def test_lint_detects_missing_properties(self):
        """Lint detects missing properties field."""
        schema = {
            "type": "object",
            "required": [],
            "additionalProperties": False
            # Missing properties
        }
        violations = lint_schema(schema)
        assert any(v.rule == "properties_missing" for v in violations)

    def test_lint_detects_incomplete_required(self):
        """Lint detects required not containing all property keys."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"}
            },
            "required": ["name"],  # Missing "age"
            "additionalProperties": False
        }
        violations = lint_schema(schema)
        assert any(v.rule == "required_incomplete" for v in violations)
        assert "age" in violations[0].message

    def test_lint_detects_array_missing_items(self):
        """Lint detects arrays without items field."""
        schema = {
            "type": "array"
            # Missing items
        }
        violations = lint_schema(schema)
        assert any(v.rule == "array_items_missing" for v in violations)

    def test_lint_detects_root_anyof(self):
        """Lint detects root-level anyOf."""
        schema = {
            "anyOf": [
                {"type": "string"},
                {"type": "integer"}
            ]
        }
        violations = lint_schema(schema)
        assert any(v.rule == "root_anyOf" for v in violations)

    def test_lint_detects_root_oneof(self):
        """Lint detects root-level oneOf."""
        schema = {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"}
            ]
        }
        violations = lint_schema(schema)
        assert any(v.rule == "root_oneOf" for v in violations)

    def test_lint_recurses_into_properties(self):
        """Lint recursively checks nested properties."""
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"]
                    # Missing additionalProperties on nested object
                }
            },
            "required": ["nested"],
            "additionalProperties": False
        }
        violations = lint_schema(schema)
        assert any("nested" in v.path for v in violations)
        assert any(v.rule == "additionalProperties_missing" for v in violations)

    def test_lint_recurses_into_array_items(self):
        """Lint recursively checks array items."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {},
                "required": []
                # Missing additionalProperties on item object
            }
        }
        violations = lint_schema(schema)
        assert any("items" in v.path for v in violations)

    def test_lint_recurses_into_definitions(self):
        """Lint recursively checks $defs."""
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
            "$defs": {
                "MyType": {
                    "type": "object",
                    "properties": {},
                    "required": []
                    # Missing additionalProperties in definition
                }
            }
        }
        violations = lint_schema(schema)
        assert any("$defs" in v.path for v in violations)

    def test_format_violations_empty(self):
        """Format violations returns success message for empty list."""
        result = format_violations([])
        assert "✅" in result
        assert "compliant" in result.lower()

    def test_format_violations_with_violations(self):
        """Format violations produces readable report."""
        violations = [
            SchemaViolation(
                path="$.properties.meta",
                rule="additionalProperties_missing",
                message="Object must have additionalProperties",
                suggestion="Add additionalProperties: False"
            )
        ]
        result = format_violations(violations)
        assert "❌" in result
        assert "$.properties.meta" in result
        assert "additionalProperties_missing" in result
        assert "💡" in result

    def test_validate_pydantic_schema_strict_raises(self):
        """validate_pydantic_schema raises ValueError in strict mode."""
        class BadSchema(BaseModel):
            # This will have additionalProperties missing by default
            class Config:
                extra = "allow"  # Creates open schema

        with pytest.raises(ValueError) as exc_info:
            validate_pydantic_schema(BadSchema, strict=True)
        assert "violates OpenAI strict mode" in str(exc_info.value)

    def test_validate_pydantic_schema_non_strict_returns_violations(self):
        """validate_pydantic_schema returns violations in non-strict mode."""
        class BadSchema(BaseModel):
            class Config:
                extra = "allow"

        violations = validate_pydantic_schema(BadSchema, strict=False)
        assert len(violations) > 0


class TestSchemaComplianceIntegration:
    """Integration tests for schema compliance with real schemas."""

    def test_metafield_schema_passes_lint(self):
        """Metafield schema itself is compliant."""
        violations = validate_pydantic_schema(Metafield, strict=False)
        assert violations == []

    def test_output_item_schema_passes_lint(self):
        """OutputItem schema is compliant after Metafield migration."""
        violations = validate_pydantic_schema(OutputItem, strict=False)
        assert violations == []

    def test_has_item_meta_schemas_are_compliant(self):
        """Schemas using HasItemMeta are compliant."""
        class MySchema(HasItemMeta, BaseModel):
            name: str

        violations = validate_pydantic_schema(MySchema, strict=False)
        assert violations == []

    def test_complex_nested_schema_compliance(self):
        """Complex nested schemas are validated recursively."""
        class InnerSchema(BaseModel):
            value: str

        class OuterSchema(BaseModel):
            inner: InnerSchema
            meta: list[Metafield] = Field(default_factory=list)

        violations = validate_pydantic_schema(OuterSchema, strict=False)
        # Should be compliant with StrictBaseModel
        assert violations == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
