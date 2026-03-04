from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=0)
class StitchPersonaInstruction(BaseInstruction):
    """Dynamic instruction for Stitch persona and simulation context."""

    required_context_keys = frozenset({"simulation_id"})

    async def render_instruction(self) -> str | None:
        from django.core.exceptions import ObjectDoesNotExist
        from apps.simcore.models import Simulation

        simulation_id = self.context.get("simulation_id")
        try:
            sim = await Simulation.objects.aget(pk=simulation_id)
        except (TypeError, ValueError, ObjectDoesNotExist):
            return (
                "You are Stitch, a friendly AI medical education facilitator. "
                "Help students reflect on their simulation performance."
            )

        return (
            "You are Stitch, a friendly AI medical education facilitator.\n"
            f"The student just completed a simulation with patient '{sim.sim_patient_full_name}'.\n"
            "Help them reflect on their performance, answer clinical questions about the case, "
            "and provide educational context. Be warm, encouraging, and concise. "
            "Use simple, supportive language. You can reference specific moments from the conversation."
        )
