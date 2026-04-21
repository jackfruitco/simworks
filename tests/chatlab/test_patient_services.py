"""Integration tests for chatlab patient services."""

from datetime import timedelta
from pathlib import Path
import threading
import traceback

from asgiref.sync import async_to_sync
from django.utils import timezone
import pytest
import yaml

from apps.chatlab.orca.instructions import (
    PatientBaseInstruction,
    PatientInformationDisclosureInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientRecentScenarioHistoryInstruction,
    PatientReplyDetailInstruction,
    PatientSafetyBoundariesInstruction,
    PatientSchemaContractInstruction,
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


def _instantiate_service_in_thread(service_cls, *, context):
    result = {}

    def worker():
        try:
            result["service"] = service_cls(context=context)
        except Exception:
            result["traceback"] = traceback.format_exc()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert "traceback" not in result, result.get("traceback")
    return result["service"]


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Patient Services")


@pytest.fixture
def history_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        email="history@example.com",
        password="testpass123",
        role=user_role,
    )


def _set_start_timestamp(simulation, *, days_ago: int) -> None:
    timestamp = timezone.now() - timedelta(days=days_ago)
    type(simulation).objects.filter(pk=simulation.pk).update(start_timestamp=timestamp)


def _normalized_instruction(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


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
        assert PatientSafetyBoundariesInstruction in service._instruction_classes
        assert PatientInformationDisclosureInstruction in service._instruction_classes
        assert PatientSchemaContractInstruction in service._instruction_classes
        assert PatientRecentScenarioHistoryInstruction in service._instruction_classes

    def test_instruction_ordering_layers(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        names = [cls.__name__ for cls in service._instruction_classes]

        assert names.index("PatientNameInstruction") < names.index(
            "PatientSafetyBoundariesInstruction"
        )
        assert names.index("PatientSafetyBoundariesInstruction") < names.index(
            "PatientConversationBehaviorInstruction"
        )
        assert names.index("PatientConversationBehaviorInstruction") < names.index(
            "PatientInformationDisclosureInstruction"
        )
        assert names.index("PatientInformationDisclosureInstruction") < names.index(
            "PatientSchemaContractInstruction"
        )
        assert names.index("PatientSchemaContractInstruction") < names.index(
            "PatientRecentScenarioHistoryInstruction"
        )
        assert names.index("PatientRecentScenarioHistoryInstruction") < names.index(
            "PatientInitialDetailInstruction"
        )

    def test_instruction_classes_are_unique(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        names = [cls.__name__ for cls in service._instruction_classes]
        assert len(names) == len(set(names))

    def test_service_instantiates_in_fresh_thread(self):
        service = _instantiate_service_in_thread(
            GenerateInitialResponse,
            context={"simulation_id": 1},
        )

        assert PatientNameInstruction in service._instruction_classes

    def test_safety_instruction_blocks_out_of_character_admission(self):
        text = PatientSafetyBoundariesInstruction.instruction or ""
        assert "Never acknowledge being an AI" in text
        assert "are you acting?" in text

    def test_initial_instruction_requires_baseline_metadata(self):
        text = PatientInitialDetailInstruction.instruction or ""
        assert "patient_name" in text
        assert "age" in text
        assert "gender" in text
        assert "1-2 `patient_history` items" in text
        assert "Do not front-load the history of present illness" in text

    def test_disclosure_instruction_prefers_gradual_under_disclosure(self):
        text = PatientInformationDisclosureInstruction.instruction or ""
        assert "Reveal information gradually" in text
        assert "Prefer realistic under-disclosure" in text

    def test_reply_instruction_marks_metadata_optional(self):
        text = PatientReplyDetailInstruction.instruction or ""
        assert "optional after the initial turn" in text
        assert "Add metadata only when genuinely new structured facts emerge" in text
        assert text.endswith(
            "Add metadata only when genuinely new structured facts emerge, using stable keys."
        )
        assert "Answer only the question that was asked" in text

    def test_python_static_patient_instructions_match_yaml(self):
        yaml_path = (
            Path(__file__).resolve().parents[2]
            / "SimWorks/apps/chatlab/orca/instructions/patient.yaml"
        )
        with yaml_path.open(encoding="utf-8") as fh:
            yaml_data = yaml.safe_load(fh)

        yaml_instructions = {
            item["name"]: _normalized_instruction(item["instruction"])
            for item in yaml_data["instructions"]
        }
        python_instructions = {
            "PatientSafetyBoundariesInstruction": PatientSafetyBoundariesInstruction,
            "PatientConversationBehaviorInstruction": PatientBaseInstruction,
            "PatientInformationDisclosureInstruction": PatientInformationDisclosureInstruction,
            "PatientSchemaContractInstruction": PatientSchemaContractInstruction,
            "PatientInitialDetailInstruction": PatientInitialDetailInstruction,
            "PatientReplyDetailInstruction": PatientReplyDetailInstruction,
        }

        for name, instruction_cls in python_instructions.items():
            assert _normalized_instruction(instruction_cls.instruction or "") == yaml_instructions[
                name
            ]


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

    def test_service_collects_disclosure_instruction(self):
        service = GenerateReplyResponse(context={"simulation_id": 1})
        assert PatientInformationDisclosureInstruction in service._instruction_classes

    def test_instruction_ordering_layers(self):
        service = GenerateReplyResponse(context={"simulation_id": 1})
        names = [cls.__name__ for cls in service._instruction_classes]

        assert names.index("PatientConversationBehaviorInstruction") < names.index(
            "PatientInformationDisclosureInstruction"
        )
        assert names.index("PatientInformationDisclosureInstruction") < names.index(
            "PatientSchemaContractInstruction"
        )
        assert names.index("PatientSchemaContractInstruction") < names.index(
            "PatientReplyDetailInstruction"
        )


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
            "messages": [
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Reply text"}],
                    "item_meta": [],
                }
            ],
            "metadata": [],
            "llm_conditions_check": [],
        }

        parsed = PatientReplyOutputSchema.model_validate(sample_output)
        dumped = parsed.model_dump(mode="json")

        json_str = json.dumps(dumped)
        assert json_str is not None
        assert "Reply text" in json_str
        assert "image_request" in json_str


@pytest.mark.django_db
class TestPatientRecentScenarioHistoryInstruction:
    def test_render_instruction_returns_empty_when_no_usable_recent_history(self, history_user):
        from apps.simcore.models import Simulation

        current_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Current Diagnosis",
            chief_complaint="Current Complaint",
            sim_patient_full_name="Current Patient",
        )
        stale_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Remote Diagnosis",
            chief_complaint="Remote Complaint",
            sim_patient_full_name="Remote Patient",
        )
        invalid_recent_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Missing Complaint Diagnosis",
            chief_complaint="",
            sim_patient_full_name="Incomplete Patient",
        )
        _set_start_timestamp(stale_simulation, days_ago=120)
        _set_start_timestamp(invalid_recent_simulation, days_ago=7)

        service = GenerateInitialResponse(
            context={"simulation_id": current_simulation.id, "user_id": history_user.id}
        )

        rendered = async_to_sync(PatientRecentScenarioHistoryInstruction.render_instruction)(
            service
        )

        assert rendered == ""

    def test_render_instruction_includes_recent_pairs_and_anti_repeat_guidance(
        self,
        history_user,
    ):
        from apps.simcore.models import Simulation

        current_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Acute Coronary Syndrome",
            chief_complaint="Crushing chest pain",
            sim_patient_full_name="Current Patient",
        )
        recent_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Migraine",
            chief_complaint="Throbbing headache",
            sim_patient_full_name="Recent Patient",
        )
        invalid_recent_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="",
            chief_complaint="Persistent cough",
            sim_patient_full_name="Incomplete Patient",
        )
        stale_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Influenza",
            chief_complaint="Fever and body aches",
            sim_patient_full_name="Stale Patient",
        )
        _set_start_timestamp(recent_simulation, days_ago=10)
        _set_start_timestamp(invalid_recent_simulation, days_ago=5)
        _set_start_timestamp(stale_simulation, days_ago=120)

        service = GenerateInitialResponse(
            context={"simulation_id": current_simulation.id, "user_id": history_user.id}
        )

        rendered = async_to_sync(PatientRecentScenarioHistoryInstruction.render_instruction)(
            service
        )

        assert "### Recent Simulation History" in rendered
        assert '("Throbbing headache", "Migraine")' in rendered
        assert "Avoid repeating the same patient scenario" in rendered
        assert (
            "Do not generate a new case whose `(chief complaint, diagnosis)` pair matches"
            in rendered
        )
        assert '("Crushing chest pain", "Acute Coronary Syndrome")' not in rendered
        assert "Persistent cough" not in rendered
        assert '("Fever and body aches", "Influenza")' not in rendered

    def test_render_instruction_falls_back_to_simulation_user_and_excludes_stale_entries(
        self,
        history_user,
    ):
        from apps.simcore.models import Simulation

        current_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Current Diagnosis",
            chief_complaint="Current Complaint",
            sim_patient_full_name="Current Patient",
        )
        recent_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Appendicitis",
            chief_complaint="Right lower quadrant pain",
            sim_patient_full_name="Recent Patient",
        )
        stale_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Pyelonephritis",
            chief_complaint="Flank pain and fever",
            sim_patient_full_name="Stale Patient",
        )
        _set_start_timestamp(recent_simulation, days_ago=20)
        _set_start_timestamp(stale_simulation, days_ago=100)

        service = GenerateInitialResponse(context={"simulation_id": current_simulation.id})

        rendered = async_to_sync(PatientRecentScenarioHistoryInstruction.render_instruction)(
            service
        )

        assert '("Right lower quadrant pain", "Appendicitis")' in rendered
        assert '("Flank pain and fever", "Pyelonephritis")' not in rendered
