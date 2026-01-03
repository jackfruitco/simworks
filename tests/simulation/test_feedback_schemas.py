"""Tests for simulation feedback schemas.

Validates:
- HotwashInitialSchema structure
- Feedback block composition
- OpenAI compatibility
"""

import pytest
from pydantic import ValidationError

from simulation.orca.schemas.feedback import HotwashInitialSchema
from simulation.orca.schemas.output_items import (
    HotwashInitialBlock,
    CorrectDiagnosisItem,
    CorrectTreatmentPlanItem,
    PatientExperienceItem,
    OverallFeedbackItem,
)


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
                "correct_diagnosis": {
                    "key": "correct_diagnosis",
                    "value": True,
                },
                "correct_treatment_plan": {
                    "key": "correct_treatment_plan",
                    "value": False,
                },
                "patient_experience": {
                    "key": "patient_experience",
                    "value": 4,
                },
                "overall_feedback": {
                    "key": "overall_feedback",
                    "value": "Good bedside manner, but missed key symptoms.",
                },
            },
        }

        parsed = HotwashInitialSchema.model_validate(sample_output)

        # Verify structure
        assert len(parsed.llm_conditions_check) == 1
        assert parsed.metadata.correct_diagnosis.value is True
        assert parsed.metadata.correct_treatment_plan.value is False
        assert parsed.metadata.patient_experience.value == 4


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
            item = PatientExperienceItem(key="patient_experience", value=value)
            assert item.value == value

        # Invalid: negative
        with pytest.raises(ValidationError):
            PatientExperienceItem(key="patient_experience", value=-1)

        # Invalid: > 5
        with pytest.raises(ValidationError):
            PatientExperienceItem(key="patient_experience", value=6)

    def test_literal_keys_enforced(self):
        """Verify literal keys are enforced on feedback items."""
        # Correct key
        item = CorrectDiagnosisItem(key="correct_diagnosis", value=True)
        assert item.key == "correct_diagnosis"

        # Wrong key should fail
        with pytest.raises(ValidationError):
            CorrectDiagnosisItem(key="wrong_key", value=True)
