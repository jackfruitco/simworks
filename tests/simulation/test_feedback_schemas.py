"""Tests for simulation feedback schemas.

Validates:
- HotwashInitialSchema structure
- Feedback block composition
- OpenAI compatibility
"""

import pytest
from pydantic import ValidationError

from simulation.orca.schemas.feedback import HotwashInitialSchema
from simulation.orca.schemas.output_items import HotwashInitialBlock


class TestHotwashInitialSchema:
    """Tests for HotwashInitialSchema."""

    def test_schema_generates_valid_json_schema(self):
        """Verify schema can generate OpenAI-compatible JSON Schema."""
        schema_json = HotwashInitialSchema.model_json_schema()

        # Validate structure
        assert schema_json["type"] == "object"
        assert "properties" in schema_json

        # Validate fields
        assert "llm_conditions_check" in schema_json["properties"]
        assert "metadata" in schema_json["properties"]

    def test_schema_openai_compatible(self):
        """Verify schema passes OpenAI validation."""
        schema_json = HotwashInitialSchema.model_json_schema()

        # No root-level unions
        assert "anyOf" not in schema_json
        assert "oneOf" not in schema_json

        # Has properties
        assert len(schema_json["properties"]) > 0

    def test_round_trip_parse(self):
        """Verify schema can parse representative feedback output."""
        sample_output = {
            "llm_conditions_check": [
                {"key": "feedback_complete", "value": "true"}
            ],
            "metadata": {
                "correct_diagnosis": True,
                "correct_treatment_plan": False,
                "patient_experience": 4,
                "overall_feedback": "Good bedside manner, but missed key symptoms.",
            },
        }

        parsed = HotwashInitialSchema.model_validate(sample_output)

        # Verify structure
        assert len(parsed.llm_conditions_check) == 1
        assert parsed.metadata.correct_diagnosis is True
        assert parsed.metadata.correct_treatment_plan is False
        assert parsed.metadata.patient_experience == 4
        assert parsed.metadata.overall_feedback == "Good bedside manner, but missed key symptoms."


class TestHotwashInitialBlock:
    """Tests for HotwashInitialBlock structure."""

    def test_block_structure(self):
        """Verify block has all required feedback fields."""
        schema_json = HotwashInitialBlock.model_json_schema()

        required_fields = {
            "correct_diagnosis",
            "correct_treatment_plan",
            "patient_experience",
            "overall_feedback",
        }
        actual_fields = set(schema_json["properties"].keys())

        assert required_fields == actual_fields

    def test_patient_experience_range(self):
        """Verify patient_experience has 0-5 constraint."""
        # Valid: 0-5
        for value in range(6):
            block = HotwashInitialBlock(
                correct_diagnosis=True,
                correct_treatment_plan=True,
                patient_experience=value,
                overall_feedback="Test feedback",
            )
            assert block.patient_experience == value

        # Invalid: negative
        with pytest.raises(ValidationError):
            HotwashInitialBlock(
                correct_diagnosis=True,
                correct_treatment_plan=True,
                patient_experience=-1,
                overall_feedback="Test feedback",
            )

        # Invalid: > 5
        with pytest.raises(ValidationError):
            HotwashInitialBlock(
                correct_diagnosis=True,
                correct_treatment_plan=True,
                patient_experience=6,
                overall_feedback="Test feedback",
            )

    def test_field_types(self):
        """Verify correct field types for direct fields."""
        # Valid block
        block = HotwashInitialBlock(
            correct_diagnosis=True,
            correct_treatment_plan=False,
            patient_experience=4,
            overall_feedback="Good bedside manner.",
        )

        assert isinstance(block.correct_diagnosis, bool)
        assert isinstance(block.correct_treatment_plan, bool)
        assert isinstance(block.patient_experience, int)
        assert isinstance(block.overall_feedback, str)

    def test_required_fields_enforced(self):
        """Verify all fields are required."""
        # Missing overall_feedback
        with pytest.raises(ValidationError):
            HotwashInitialBlock(
                correct_diagnosis=True,
                correct_treatment_plan=True,
                patient_experience=4,
            )

    def test_overall_feedback_min_length(self):
        """Verify overall_feedback requires at least 1 character."""
        # Empty string should fail
        with pytest.raises(ValidationError):
            HotwashInitialBlock(
                correct_diagnosis=True,
                correct_treatment_plan=True,
                patient_experience=4,
                overall_feedback="",
            )
