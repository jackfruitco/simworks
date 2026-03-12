# trainerlab/orca/services/initial.py

import logging
from typing import ClassVar

from apps.simcore.orca.instructions import BaseStitchPersona
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

from ..instructions import (
    CombatMixin,
    InitialResponseMixin,
    MilitaryMedicMixin,
    TrainerLabMixin,
    TraumaMixin,
)

__all__ = ["GenerateInitialScenario"]

logger = logging.getLogger(__name__)


@orca.service
class GenerateInitialScenario(
    BaseStitchPersona,
    TrainerLabMixin,
    InitialResponseMixin,
    MilitaryMedicMixin,
    TraumaMixin,
    CombatMixin,
    DjangoBaseService,
):
    """Generate an initial AI-generated Scenario for TrainerLab."""

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from ..schemas import InitialScenarioSchema

    response_schema = InitialScenarioSchema
