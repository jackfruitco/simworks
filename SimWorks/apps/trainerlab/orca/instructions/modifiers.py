"""Modifier instruction classes for TrainerLab services."""

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=50)
class MilitaryMedicMixin(NsMixin, BaseInstruction):
    group = "modifier"
    instruction = "The trainee is a U.S. Military Medic."


@orca.instruction(order=50)
class CombatMixin(NsMixin, BaseInstruction):
    group = "modifier"
    instruction = "Scenario Rule: must be a combat scenario."


@orca.instruction(order=50)
class TraumaMixin(NsMixin, BaseInstruction):
    group = "modifier"
    instruction = "Scenario Rule: must be a trauma scenario."
