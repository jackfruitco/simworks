"""Dynamic instruction classes for Stitch facilitator service.

Static instructions are defined in stitch.yaml (same directory).
"""

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from apps.simcore.models import Simulation
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class StitchPersonaInstruction(BaseInstruction):
    async def render_instruction(self) -> str:
        simulation_id = self.context.get("simulation_id")

        try:
            sim = await Simulation.objects.aget(pk=simulation_id)
        except (TypeError, ValueError, ObjectDoesNotExist):
            return (
                "You are Stitch, a friendly AI medical education facilitator. "
                "Help the student reflect on their simulation performance."
            )

        return (
            "You are Stitch, a friendly AI medical education facilitator.\n"
            f"The student just completed a simulation with patient '{sim.sim_patient_full_name}'.\n"
            "Help the student reflect on their performance, answer clinical questions about the case, "
            "and provide educational context. Be warm, encouraging, and concise."
        )


@orca.instruction(order=60)
class StitchConversationContextInstruction(BaseInstruction):
    async def render_instruction(self) -> str:
        simulation_id = self.context.get("simulation_id")

        try:
            sim = await Simulation.objects.aget(pk=simulation_id)
        except (TypeError, ValueError, ObjectDoesNotExist):
            return ""

        history = await sync_to_async(sim.history)()
        if not history:
            return ""

        lines = []
        for entry in history[-20:]:
            role = entry.get("role", "?")
            content = entry.get("content", "")
            lines.append(f"[{role}]: {content}")

        return "### Simulation Conversation History\n" + "\n".join(lines)
