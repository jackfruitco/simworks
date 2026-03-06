"""Integration tests for chatlab patient services."""

from apps.chatlab.orca.instructions import (
    PatientBaseInstruction,
    PatientNameInstruction,
)
from apps.chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
)
from apps.chatlab.orca.services.patient import (
    GenerateImageResponse,
    GenerateInitialResponse,
    GenerateReplyResponse,
)


class TestGenerateInitialResponseService:
    def test_service_has_response_schema(self):
        assert hasattr(GenerateInitialResponse, "response_schema")
        assert GenerateInitialResponse.response_schema == PatientInitialOutputSchema

    def test_service_required_context_keys(self):
        assert hasattr(GenerateInitialResponse, "required_context_keys")
        assert "simulation_id" in GenerateInitialResponse.required_context_keys

    def test_service_collects_instruction_classes(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        assert PatientNameInstruction in service._instruction_classes
        assert PatientBaseInstruction in service._instruction_classes


class TestGenerateReplyResponseService:
    def test_service_has_response_schema(self):
        assert hasattr(GenerateReplyResponse, "response_schema")
        assert GenerateReplyResponse.response_schema == PatientReplyOutputSchema

    def test_service_does_not_have_response_format_cls(self):
        response_format_cls = getattr(GenerateReplyResponse, "response_format_cls", None)
        assert response_format_cls is None

    def test_service_required_context_keys(self):
        assert hasattr(GenerateReplyResponse, "required_context_keys")
        assert "simulation_id" in GenerateReplyResponse.required_context_keys


class TestGenerateImageResponseService:
    def test_service_required_context_keys(self):
        assert hasattr(GenerateImageResponse, "required_context_keys")
        assert "simulation_id" in GenerateImageResponse.required_context_keys


class TestSchemaSerializability:
    def test_initial_schema_model_dump_is_serializable(self):
        import json

        sample_output = {
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Hello"}],
                    "item_meta": [],
                }
            ],
            "metadata": [],
            "llm_conditions_check": [],
        }

        parsed = PatientInitialOutputSchema.model_validate(sample_output)
        dumped = parsed.model_dump(mode="json")

        json_str = json.dumps(dumped)
        assert json_str is not None
        assert "Hello" in json_str

    def test_reply_schema_model_dump_is_serializable(self):
        import json

        sample_output = {
            "image_requested": False,
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Reply text"}],
                    "item_meta": [],
                }
            ],
            "llm_conditions_check": [],
        }

        parsed = PatientReplyOutputSchema.model_validate(sample_output)
        dumped = parsed.model_dump(mode="json")

        json_str = json.dumps(dumped)
        assert json_str is not None
        assert "Reply text" in json_str
        assert "image_requested" in json_str
