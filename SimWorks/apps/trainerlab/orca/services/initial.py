# trainerlab/orca/services/initial.py

import logging
from typing import ClassVar

from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

__all__ = ["GenerateInitialScenario"]

logger = logging.getLogger(__name__)


@orca.service
class GenerateInitialScenario(DjangoBaseService):
    """Generate an initial AI-generated Scenario for TrainerLab."""

    instruction_refs: ClassVar[list[str]] = [
        "simcore.stitch.BaseStitchPersona",
        "trainerlab.initial.TrainerLabMixin",
        "trainerlab.initial.InitialResponseMixin",
        "trainerlab.initial.InjuryCodebookMixin",
        "trainerlab.modifier.MilitaryMedicMixin",
        "trainerlab.modifier.TraumaMixin",
        "trainerlab.modifier.CombatMixin",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from ..schemas import InitialScenarioSchema

    response_schema = InitialScenarioSchema
