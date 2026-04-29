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
    PatientRecentScenarioHistoryInstruction,
    patient as patient_instruction_module,
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

STATIC_PATIENT_INSTRUCTION_NAMES = (
    "PatientSafetyBoundariesInstruction",
    "PatientConversationBehaviorInstruction",
    "PatientInformationDisclosureInstruction",
    "PatientSchemaContractInstruction",
    "PatientInitialDetailInstruction",
    "PatientReplyDetailInstruction",
)

EXPECTED_INITIAL_INSTRUCTION_NAMES = (
    "PatientNameInstruction",
    "PatientModifierInstruction",
    "PatientSafetyBoundariesInstruction",
    "PatientConversationBehaviorInstruction",
    "PatientInformationDisclosureInstruction",
    "PatientSchemaContractInstruction",
    "PatientRecentScenarioHistoryInstruction",
    "PatientInitialDetailInstruction",
)

EXPECTED_REPLY_INSTRUCTION_NAMES = (
    "PatientNameInstruction",
    "PatientSafetyBoundariesInstruction",
    "PatientConversationBehaviorInstruction",
    "PatientInformationDisclosureInstruction",
    "PatientSchemaContractInstruction",
    "PatientReplyDetailInstruction",
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


def _instruction_names(service) -> tuple[str, ...]:
    return tuple(cls.__name__ for cls in service._instruction_classes)


def _instruction_by_name(service, name: str):
    for instruction_cls in service._instruction_classes:
        if instruction_cls.__name__ == name:
            return instruction_cls
    raise AssertionError(f"Instruction {name!r} was not resolved")


def _yaml_instruction_text(name: str) -> str:
    yaml_path = (
        Path(__file__).resolve().parents[2] / "SimWorks/apps/chatlab/orca/instructions/patient.yaml"
    )
    with yaml_path.open(encoding="utf-8") as fh:
        yaml_data = yaml.safe_load(fh)

    for item in yaml_data["instructions"]:
        if item["name"] == name:
            return item["instruction"]
    raise AssertionError(f"Instruction {name!r} was not found in patient.yaml")


class TestGenerateInitialResponseService:
    def test_service_has_response_schema(self):
        assert hasattr(GenerateInitialResponse, "response_schema")
        assert GenerateInitialResponse.response_schema == PatientInitialOutputSchema

    def test_service_required_context_keys(self):
        assert hasattr(GenerateInitialResponse, "required_context_keys")
        assert "simulation_id" in GenerateInitialResponse.required_context_keys

    def test_service_collects_instruction_classes(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        names = _instruction_names(service)
        assert "PatientNameInstruction" in names
        assert "PatientRecentScenarioHistoryInstruction" in names

    def test_resolves_expected_instruction_names_in_order(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        assert _instruction_names(service) == EXPECTED_INITIAL_INSTRUCTION_NAMES

    def test_instruction_classes_are_unique(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        names = _instruction_names(service)
        assert len(names) == len(set(names))

    def test_service_instantiates_in_fresh_thread(self):
        service = _instantiate_service_in_thread(
            GenerateInitialResponse,
            context={"simulation_id": 1},
        )

        assert "PatientNameInstruction" in _instruction_names(service)

    def test_safety_instruction_blocks_out_of_character_admission(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientSafetyBoundariesInstruction")
        text = instruction_cls.instruction or ""
        assert "Never acknowledge being an AI" in text
        assert "are you acting?" in text

    def test_initial_instruction_requires_baseline_metadata(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInitialDetailInstruction")
        text = instruction_cls.instruction or ""
        assert "patient_name" in text
        assert "age" in text
        assert "gender" in text
        assert "1-2 `patient_history` items" in text
        assert "Do not front-load the history of present illness" in text

    def test_disclosure_instruction_prefers_gradual_under_disclosure(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInformationDisclosureInstruction")
        text = instruction_cls.instruction or ""
        assert "Reveal information gradually" in text
        assert "Prefer realistic under-disclosure" in text

    def test_medication_box_scenario_includes_patient_environment_boundaries(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInformationDisclosureInstruction")
        text = instruction_cls.instruction or ""
        assert "Speak only from the patient's own perspective" in text
        assert "Do not ask the clinician/user to provide images" in text
        assert "medication box" in text
        assert (
            "The patient should never request any action whose main purpose is to help the model obtain missing context."
            in text
        )

    def test_disclosure_instruction_lists_disallowed_role_inversion_requests(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInformationDisclosureInstruction")
        text = instruction_cls.instruction or ""
        assert "Can you send me a picture of the bottle?" in text
        assert "Upload the ingredient list so I can check it." in text
        assert "Can you inspect the box for me?" in text
        assert "Can you look at the label and tell me what it says?" in text

    def test_disclosure_instruction_lists_allowed_patient_perspective_outputs(self):
        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInformationDisclosureInstruction")
        text = instruction_cls.instruction or ""
        assert "Hold on, I have the box here... it says acetaminophen 500 mg." in text
        assert "I can't find the bottle right now." in text
        assert "The label is smudged; I can't really read it." in text
        assert "It's a small white bottle with a blue cap." in text

    def test_reply_instruction_marks_metadata_optional(self):
        service = GenerateReplyResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientReplyDetailInstruction")
        text = instruction_cls.instruction or ""
        assert "optional after the initial turn" in text
        assert "Add metadata only when genuinely new structured facts emerge" in text
        assert text.rstrip().endswith(
            "Add metadata only when genuinely new structured facts emerge, using stable keys."
        )
        assert "Answer only the question that was asked" in text

    def test_static_patient_instructions_are_yaml_backed(self):
        for name in STATIC_PATIENT_INSTRUCTION_NAMES:
            assert not hasattr(patient_instruction_module, name)

        service = GenerateInitialResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInformationDisclosureInstruction")

        assert instruction_cls.instruction == _yaml_instruction_text(
            "PatientInformationDisclosureInstruction"
        )
        assert "Reveal information gradually" in instruction_cls.instruction


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
        assert "PatientInformationDisclosureInstruction" in _instruction_names(service)

    def test_resolves_expected_instruction_names_in_order(self):
        service = GenerateReplyResponse(context={"simulation_id": 1})
        assert _instruction_names(service) == EXPECTED_REPLY_INSTRUCTION_NAMES

    def test_reply_path_includes_same_patient_environment_boundary_instruction(self):
        service = GenerateReplyResponse(context={"simulation_id": 1})
        instruction_cls = _instruction_by_name(service, "PatientInformationDisclosureInstruction")
        text = instruction_cls.instruction or ""
        assert "Do not ask the clinician/user to provide images" in text
        assert (
            "The patient must never ask the clinician to look at, upload, inspect, or retrieve such an object on the patient's behalf."
            in text
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

    def test_resolves_user_via_user_id_when_bare_simulation_cached_in_context(
        self,
        history_user,
    ):
        """Regression: PatientRecentScenarioHistoryInstruction must not trigger lazy FK access.

        In production, PatientModifierInstruction (order=5) runs before this instruction and
        caches the simulation in context.  Before the fix, if that cached simulation was fetched
        without select_related("user"), accessing simulation.user inside an async service call
        would raise SynchronousOnlyOperation.

        This test verifies the instruction resolves the user via the user_id context primitive
        (Fix 2) so it never needs to traverse the simulation.user FK at all.
        """
        from apps.simcore.models import Simulation

        current_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Current Diagnosis",
            chief_complaint="Current Complaint",
            sim_patient_full_name="Current Patient",
        )
        recent_simulation = Simulation.objects.create(
            user=history_user,
            diagnosis="Pneumonia",
            chief_complaint="Shortness of breath",
            sim_patient_full_name="Recent Patient",
        )
        _set_start_timestamp(recent_simulation, days_ago=15)

        # Simulate what PatientModifierInstruction used to do before Fix 1:
        # fetch simulation bare (no select_related) and cache it to context.
        bare_simulation = Simulation.objects.get(pk=current_simulation.pk)

        service = GenerateInitialResponse(
            context={
                "simulation_id": current_simulation.id,
                "user_id": history_user.id,
                "simulation": bare_simulation,  # cached without select_related("user")
            }
        )

        # The instruction must resolve user via user_id, not via bare_simulation.user.
        rendered = async_to_sync(PatientRecentScenarioHistoryInstruction.render_instruction)(
            service
        )

        assert '("Shortness of breath", "Pneumonia")' in rendered

    def test_patient_modifier_instruction_caches_simulation_with_user_preloaded(
        self,
        history_user,
    ):
        """Regression: PatientModifierInstruction must select_related("user") when caching.

        Before Fix 1, PatientModifierInstruction cached a bare simulation (no select_related).
        PatientRecentScenarioHistoryInstruction (order=80) would then try simulation.user on
        that bare object inside an async context, causing SynchronousOnlyOperation in production.

        This test verifies that after PatientModifierInstruction runs, the simulation stored in
        context has the user FK already loaded (no lazy DB hit needed).
        """
        from apps.chatlab.orca.instructions import PatientModifierInstruction
        from apps.simcore.models import Simulation

        simulation = Simulation.objects.create(
            user=history_user,
            sim_patient_full_name="Test Patient",
        )

        service = GenerateInitialResponse(context={"simulation_id": simulation.id})

        async_to_sync(PatientModifierInstruction.render_instruction)(service)

        cached = service.context.get("simulation")
        assert cached is not None, "PatientModifierInstruction must cache simulation in context"
        # Accessing .user must not require a DB round-trip; verify the field descriptor
        # does not indicate a deferred/non-loaded state.
        assert cached.user_id == history_user.id
        # If user was not select_related, cached.user would trigger a sync ORM query here.
        # After Fix 1, it is pre-loaded so this access is safe.
        assert cached.user is not None
        assert cached.user.pk == history_user.pk
