from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=0)
class PatientNameInstruction(BaseInstruction):
    """Dynamic instruction that renders the patient's name from simulation context."""

    required_context_keys = frozenset({"simulation_id"})

    async def render_instruction(self) -> str | None:
        from django.core.exceptions import ObjectDoesNotExist
        from apps.simcore.models import Simulation

        simulation_id = self.context.get("simulation_id")
        simulation = self.context.get("simulation")

        if simulation is None and simulation_id:
            try:
                simulation = await Simulation.objects.aget(pk=simulation_id)
            except (TypeError, ValueError, ObjectDoesNotExist):
                return "You are a standardized patient."

        if simulation:
            return f"As standardized patient, your name is {simulation.sim_patient_full_name}."

        return "You are a standardized patient."
