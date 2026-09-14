import threading
import traceback

from apps.simcore.orca.instructions import BaseStitchPersona
from apps.trainerlab.orca.instructions import (
    InjuryCodebookMixin,
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


def _instruction_by_name(service, name: str):
    for instruction_cls in service._instruction_classes:
        if instruction_cls.__name__ == name:
            return instruction_cls
    raise AssertionError(f"Instruction {name!r} was not resolved")


class TestGenerateInitialScenarioService:
    def test_service_instantiates_and_collects_instructions(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})

        assert service.required_context_keys == ("simulation_id",)
        assert BaseStitchPersona in service._instruction_classes
        assert _instruction_by_name(service, "TrainerLabMixin")
        assert _instruction_by_name(service, "InitialResponseMixin")
        assert _instruction_by_name(service, "InjuryCodebookMixin")

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
        assert "Recommendation Compatibility" in codebook
        assert "`hypoperfusion_shock`" in codebook
        assert "`iv_access`" in codebook
        assert "`io_access`" in codebook

    def test_initial_response_instruction_requests_scenario_brief(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})
        instruction = _instruction_by_name(service, "InitialResponseMixin").instruction

        assert "scenario_brief" in instruction
        assert "instructor read-aloud" in instruction
        assert "evacuation" in instruction
        assert "each targets exactly one problem by `target_problem_ref`" in instruction
        assert "Do not create `performed_interventions`" in instruction

    def test_service_instantiates_in_fresh_thread(self):
        service = _instantiate_service_in_thread(
            GenerateInitialScenario,
            context={"simulation_id": 1},
        )

        assert _instruction_by_name(service, "InjuryCodebookMixin")

    def test_vitals_service_uses_derived_service_identity(self):
        assert GenerateVitalsProgression.identity.as_str == (
            "services.trainerlab.default.vitals-progression"
        )
