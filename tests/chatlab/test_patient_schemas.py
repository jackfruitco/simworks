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
from simulation.orca.schemas.output_items import LLMConditionsCheckItem
from simulation.orca.schemas.metadata_items import (
    LabResultItem,
    RadResultItem,
    PatientHistoryItem,
    PatientDemographicsItem,
    SimulationMetadataItem,
)


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

    def test_schema_is_pydantic_model(self):
        """Verify schema is a valid Pydantic BaseModel (no @schema decorator needed for Pydantic AI)."""
        # These are plain Pydantic models - Pydantic AI handles validation natively
        assert hasattr(PatientInitialOutputSchema, "model_validate")
        assert hasattr(PatientInitialOutputSchema, "model_json_schema")
        assert hasattr(PatientInitialOutputSchema, "model_config")

    def test_schema_round_trip_parse(self):
        """Verify schema can parse representative OpenAI output with polymorphic metadata."""
        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello, I'm the patient."}],
                    "item_meta": [],
                }
            ],
            # PatientInitialOutputSchema.metadata is list[MetadataItem] (polymorphic union)
            "metadata": [
                {
                    "kind": "patient_demographics",
                    "key": "age",
                    "value": "45"
                },
                {
                    "kind": "patient_demographics",
                    "key": "gender",
                    "value": "Male"
                },
            ],
            "llm_conditions_check": [
                {"key": "ready_for_questions", "value": "true"}
            ],
        }

        # Parse
        parsed = PatientInitialOutputSchema.model_validate(sample_output)

        # Verify messages structure
        assert len(parsed.messages) == 1
        assert parsed.messages[0].content[0].text == "Hello, I'm the patient."

        # Verify metadata as list[MetadataItem] (polymorphic)
        assert len(parsed.metadata) == 2
        assert isinstance(parsed.metadata[0], PatientDemographicsItem)
        assert parsed.metadata[0].key == "age"
        assert parsed.metadata[0].value == "45"
        assert parsed.metadata[0].kind == "patient_demographics"

        assert isinstance(parsed.metadata[1], PatientDemographicsItem)
        assert parsed.metadata[1].key == "gender"
        assert parsed.metadata[1].value == "Male"

        assert len(parsed.llm_conditions_check) == 1
        assert parsed.llm_conditions_check[0].key == "ready_for_questions"

    def test_schema_rejects_extra_fields(self):
        """Verify strict mode rejects extra keys (StrictBaseModel)."""
        invalid_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Test"}],
                    "item_meta": [],
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

    def test_polymorphic_lab_result_metadata(self):
        """Verify LabResultItem with all required fields."""
        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Here are your lab results."}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {
                    "kind": "lab_result",
                    "key": "Hemoglobin",
                    "value": "14.5",
                    "panel_name": "Complete Blood Count",
                    "result_unit": "g/dL",
                    "reference_range_low": "12.0",
                    "reference_range_high": "16.0",
                    "result_flag": "normal",
                    "result_comment": "Within normal limits"
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientInitialOutputSchema.model_validate(sample_output)
        assert len(parsed.metadata) == 1
        lab_result = parsed.metadata[0]

        assert isinstance(lab_result, LabResultItem)
        assert lab_result.kind == "lab_result"
        assert lab_result.key == "Hemoglobin"
        assert lab_result.value == "14.5"
        assert lab_result.panel_name == "Complete Blood Count"
        assert lab_result.result_unit == "g/dL"
        assert lab_result.result_flag == "normal"
        assert lab_result.__orm_model__ == "simulation.LabResult"

    def test_polymorphic_rad_result_metadata(self):
        """Verify RadResultItem with required fields."""
        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Here are your radiology results."}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {
                    "kind": "rad_result",
                    "key": "Chest X-Ray",
                    "value": "No acute cardiopulmonary disease",
                    "result_flag": "normal"
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientInitialOutputSchema.model_validate(sample_output)
        assert len(parsed.metadata) == 1
        rad_result = parsed.metadata[0]

        assert isinstance(rad_result, RadResultItem)
        assert rad_result.kind == "rad_result"
        assert rad_result.key == "Chest X-Ray"
        assert rad_result.result_flag == "normal"
        assert rad_result.__orm_model__ == "simulation.RadResult"

    def test_polymorphic_patient_history_metadata(self):
        """Verify PatientHistoryItem with required fields."""
        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Tell me about your medical history."}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {
                    "kind": "patient_history",
                    "key": "Hypertension",
                    "value": "Diagnosed with essential hypertension",
                    "is_resolved": False,
                    "duration": "5 years"
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientInitialOutputSchema.model_validate(sample_output)
        assert len(parsed.metadata) == 1
        history = parsed.metadata[0]

        assert isinstance(history, PatientHistoryItem)
        assert history.kind == "patient_history"
        assert history.key == "Hypertension"
        assert history.is_resolved is False
        assert history.duration == "5 years"
        assert history.__orm_model__ == "simulation.PatientHistory"

    def test_polymorphic_mixed_metadata_types(self):
        """Verify multiple metadata types in single schema."""
        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello"}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {
                    "kind": "patient_demographics",
                    "key": "age",
                    "value": "65"
                },
                {
                    "kind": "patient_history",
                    "key": "Diabetes Type 2",
                    "value": "Controlled with metformin",
                    "is_resolved": False,
                    "duration": "10 years"
                },
                {
                    "kind": "lab_result",
                    "key": "Glucose",
                    "value": "110",
                    "result_unit": "mg/dL",
                    "reference_range_low": "70",
                    "reference_range_high": "100",
                    "result_flag": "abnormal",
                    "result_comment": "Slightly elevated"
                },
                {
                    "kind": "generic",
                    "key": "notes",
                    "value": "Patient cooperative and alert"
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientInitialOutputSchema.model_validate(sample_output)
        assert len(parsed.metadata) == 4

        # Verify discriminated union resolved correctly
        assert isinstance(parsed.metadata[0], PatientDemographicsItem)
        assert isinstance(parsed.metadata[1], PatientHistoryItem)
        assert isinstance(parsed.metadata[2], LabResultItem)
        assert isinstance(parsed.metadata[3], SimulationMetadataItem)

        # Verify each has correct __orm_model__
        assert parsed.metadata[0].__orm_model__ == "simulation.PatientDemographics"
        assert parsed.metadata[1].__orm_model__ == "simulation.PatientHistory"
        assert parsed.metadata[2].__orm_model__ == "simulation.LabResult"
        assert parsed.metadata[3].__orm_model__ == "simulation.SimulationMetadata"

    def test_polymorphic_metadata_discriminator_validation(self):
        """Verify invalid 'kind' discriminator is rejected."""
        invalid_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Test"}],
                    "item_meta": [],
                }
            ],
            "metadata": [
                {
                    "kind": "invalid_kind",  # Invalid discriminator
                    "key": "test",
                    "value": "test"
                }
            ],
            "llm_conditions_check": [],
        }

        with pytest.raises(ValidationError) as exc_info:
            PatientInitialOutputSchema.model_validate(invalid_output)

        error_str = str(exc_info.value).lower()
        assert "discriminator" in error_str or "kind" in error_str


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
                    "content": [{"type": "text", "text": "Here's an X-ray..."}],
                    "item_meta": [],
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
        # PatientResultsOutputSchema.metadata is list[ResultMessageItem]
        # (complex items with content and item_meta)
        sample_output = {
            "metadata": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Final diagnosis: ..."}],
                    "item_meta": [
                        {"key": "key", "value": "final_diagnosis"}
                    ],
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientResultsOutputSchema.model_validate(sample_output)
        assert len(parsed.metadata) == 1
        # Verify item_meta as list[ResultMetafield]
        meta_keys = {mf.key: mf.value for mf in parsed.metadata[0].item_meta}
        assert meta_keys["key"] == "final_diagnosis"
