# trainerlab/orca/instructions/modifiers.py


from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca
from orchestrai_django.identity import DjangoIdentityMixin

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


class ModifierGroupMixin(DjangoIdentityMixin):
    group = "modifier"


@orca.instruction
class MilitaryMedicMixin(NsMixin, ModifierGroupMixin, BaseInstruction):
    instruction = "The trainee is a U.S. Military Medic. "


@orca.instruction
class SpecOpsMedicMixin(NsMixin, ModifierGroupMixin, BaseInstruction):
    instruction = "The trainee is a U.S. Military Special Operations Medic. "


@orca.instruction
class TraumaMixin(NsMixin, ModifierGroupMixin, BaseInstruction):
    instruction = "Scenario Rule: must be a trauma scenario. "


@orca.instruction
class MedicalMixin(NsMixin, ModifierGroupMixin, BaseInstruction):
    instruction = "Scenario Rule: must be a medical scenario. "


@orca.instruction
class CombatMixin(NsMixin, ModifierGroupMixin, BaseInstruction):
    instruction = "Scenario Rule: must be a combat scenario. "
