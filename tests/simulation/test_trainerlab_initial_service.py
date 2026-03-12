from apps.simcore.orca.instructions import BaseStitchPersona
from apps.trainerlab.orca.instructions import InitialResponseMixin, TrainerLabMixin
from apps.trainerlab.orca.services import GenerateInitialScenario


class TestGenerateInitialScenarioService:
    def test_service_instantiates_and_collects_instructions(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})

        assert service.required_context_keys == ("simulation_id",)
        assert BaseStitchPersona in service._instruction_classes
        assert TrainerLabMixin in service._instruction_classes
        assert InitialResponseMixin in service._instruction_classes

    def test_service_instruction_ordering(self):
        service = GenerateInitialScenario(context={"simulation_id": 1})
        names = [cls.__name__ for cls in service._instruction_classes]

        assert names.index("BaseStitchPersona") < names.index("TrainerLabMixin")
        assert names.index("TrainerLabMixin") < names.index("InitialResponseMixin")
