import threading
import traceback

from apps.simcore.orca.instructions import BaseStitchPersona
from apps.trainerlab.orca.instructions import (
    InitialResponseMixin,
    InjuryCodebookMixin,
    TrainerLabMixin,
)
from apps.trainerlab.orca.services import GenerateInitialScenario, GenerateVitalsProgression


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


class TestGenerateInitialScenarioService:
    def test_service_instantiates_and_collects_instructions(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})

        assert service.required_context_keys == ("simulation_id",)
        assert BaseStitchPersona in service._instruction_classes
        assert TrainerLabMixin in service._instruction_classes
        assert InitialResponseMixin in service._instruction_classes
        assert InjuryCodebookMixin in service._instruction_classes

    def test_service_instruction_ordering(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})
        names = [cls.__name__ for cls in service._instruction_classes]

        assert names.index("BaseStitchPersona") < names.index("TrainerLabMixin")
        assert names.index("TrainerLabMixin") < names.index("InitialResponseMixin")
        assert names.index("InitialResponseMixin") < names.index("InjuryCodebookMixin")

    def test_injury_codebook_instruction_contains_canonical_examples(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})
        codebook = InjuryCodebookMixin.render_instruction(service)

        assert "Injury Codebook" in codebook
        assert "M=Massive Hemorrhage" in codebook
        assert "HLA=Left Anterior Head" in codebook
        assert "LAC=Laceration" in codebook

    def test_initial_response_instruction_requests_scenario_brief(self):
        instruction = InitialResponseMixin.instruction

        assert "scenario_brief" in instruction
        assert "read out loud to the trainee" in instruction
        assert "evacuation options" in instruction

    def test_service_instantiates_in_fresh_thread(self):
        service = _instantiate_service_in_thread(
            GenerateInitialScenario,
            context={"simulation_id": 1},
        )

        assert InjuryCodebookMixin in service._instruction_classes

    def test_vitals_service_uses_derived_service_identity(self):
        assert GenerateVitalsProgression.identity.as_str == (
            "services.trainerlab.default.vitals-progression"
        )
