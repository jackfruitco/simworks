"""Tests for chatlab patient schemas.

Validates:
- JSON Schema generation
- OpenAI compatibility
- Round-trip parsing
- Strict mode enforcement
"""

import pytest
from pydantic import ValidationError

from chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from orchestrai_django.types import DjangoOutputItem
from orchestrai.types.content import OutputTextContent
from simulation.orca.schemas.output_items import LLMConditionsCheckItem


class TestPatientInitialSchema:
    """Tests for PatientInitialOutputSchema."""

    def test_schema_generates_valid_json_schema(self):
        """Verify schema can generate OpenAI-compatible JSON Schema."""
        schema_json = PatientInitialOutputSchema.model_json_schema()

        # Validate structure
        assert schema_json["type"] == "object"
        assert "properties" in schema_json
        assert "required" in schema_json

        # Validate required fields present
        assert "messages" in schema_json["properties"]
        assert "metadata" in schema_json["properties"]
        assert "llm_conditions_check" in schema_json["properties"]

        # Validate messages is array with min 1
        messages_prop = schema_json["properties"]["messages"]
        assert messages_prop["type"] == "array"
        assert messages_prop.get("minItems") == 1

    def test_schema_openai_compatible(self):
        """Verify schema passes OpenAI validation."""
        schema_json = PatientInitialOutputSchema.model_json_schema()

        # Check root is object (not union/array)
        assert schema_json["type"] == "object"

        # Check no root-level unions
        assert "anyOf" not in schema_json
        assert "oneOf" not in schema_json

        # Check has properties
        assert len(schema_json["properties"]) > 0

    def test_schema_has_provider_compatibility(self):
        """Verify schema was validated and tagged by @schema decorator."""
        assert hasattr(PatientInitialOutputSchema, "_provider_compatibility")
        assert PatientInitialOutputSchema._provider_compatibility.get("openai") is True

        assert hasattr(PatientInitialOutputSchema, "_validated_schema")
        assert isinstance(PatientInitialOutputSchema._validated_schema, dict)

    def test_schema_round_trip_parse(self):
        """Verify schema can parse representative OpenAI output."""
        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Hello, I'm the patient."}],
                    "item_meta": {},
                }
            ],
            "metadata": [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Patient age: 45"}],
                    "item_meta": {"key": "age", "type": "demographic"},
                }
            ],
            "llm_conditions_check": [
                {"key": "ready_for_questions", "value": "true"}
            ],
        }

        # Parse
        parsed = PatientInitialOutputSchema.model_validate(sample_output)

        # Verify structure
        assert len(parsed.messages) == 1
        assert parsed.messages[0].content[0].text == "Hello, I'm the patient."

        assert len(parsed.metadata) == 1
        assert parsed.metadata[0].item_meta["key"] == "age"

        assert len(parsed.llm_conditions_check) == 1
        assert parsed.llm_conditions_check[0].key == "ready_for_questions"

    def test_schema_rejects_extra_fields(self):
        """Verify strict mode rejects extra keys (StrictBaseModel)."""
        invalid_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Test"}],
                }
            ],
            "metadata": [],
            "llm_conditions_check": [],
            "extra_field": "should_fail",  # Extra field
        }

        with pytest.raises(ValidationError) as exc_info:
            PatientInitialOutputSchema.model_validate(invalid_output)

        assert "extra_field" in str(exc_info.value).lower()

    def test_schema_requires_min_one_message(self):
        """Verify messages field requires at least one item."""
        invalid_output = {
            "messages": [],  # Empty - should fail
            "metadata": [],
            "llm_conditions_check": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            PatientInitialOutputSchema.model_validate(invalid_output)

        # Should mention minItems or list constraint
        error_str = str(exc_info.value).lower()
        assert "message" in error_str or "list" in error_str


class TestPatientReplySchema:
    """Tests for PatientReplyOutputSchema."""

    def test_schema_structure(self):
        """Verify reply schema has expected fields."""
        schema_json = PatientReplyOutputSchema.model_json_schema()

        required_fields = {"image_requested", "messages", "llm_conditions_check"}
        actual_fields = set(schema_json["properties"].keys())

        assert required_fields.issubset(actual_fields)

    def test_image_requested_field(self):
        """Verify image_requested is boolean."""
        schema_json = PatientReplyOutputSchema.model_json_schema()
        assert schema_json["properties"]["image_requested"]["type"] == "boolean"

    def test_round_trip_with_image_requested(self):
        """Verify parsing with image_requested=True."""
        sample_output = {
            "image_requested": True,
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Here's an X-ray..."}],
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientReplyOutputSchema.model_validate(sample_output)
        assert parsed.image_requested is True


class TestPatientResultsSchema:
    """Tests for PatientResultsOutputSchema."""

    def test_schema_structure(self):
        """Verify results schema has expected fields."""
        schema_json = PatientResultsOutputSchema.model_json_schema()

        required_fields = {"metadata", "llm_conditions_check"}
        actual_fields = set(schema_json["properties"].keys())

        assert required_fields.issubset(actual_fields)

    def test_round_trip_with_metadata(self):
        """Verify parsing with metadata items."""
        sample_output = {
            "metadata": [
                {
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Final diagnosis: ..."}],
                    "item_meta": {"key": "final_diagnosis"},
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientResultsOutputSchema.model_validate(sample_output)
        assert len(parsed.metadata) == 1
