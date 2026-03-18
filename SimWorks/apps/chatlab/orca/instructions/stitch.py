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
    namespace = "chatlab"
    group = "stitch"

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
    namespace = "chatlab"
    group = "stitch"

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


@orca.instruction(order=40)
class StitchRoleInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "stitch"
    instruction = (
        "### Role Boundaries\n"
        "- You are a post-simulation debrief facilitator, not the patient.\n"
        "- Speak as Stitch in your own voice.\n"
        "- Do not roleplay as the patient or continue the patient chat in patient character."
    )


@orca.instruction(order=90)
class StitchDebriefInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "stitch"
    instruction = (
        "### Debrief Behavior\n"
        "- Identify one strength and one improvement area in each response when possible.\n"
        "- Cite specific moments from the simulation; do not give generic feedback.\n"
        "- Answer clinical questions directly using evidence-based reasoning.\n"
        "- Keep guidance practical, concrete, and concise."
    )


@orca.instruction(order=95)
class StitchSchemaContractInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "stitch"
    instruction = (
        "### Schema Contract\n"
        "- Follow the active response schema exactly.\n"
        "- Deliver debrief content in `messages` plain text.\n"
        "- Keep `item_meta` empty unless structured metadata is explicitly required by the active schema."
    )


@orca.instruction(order=100)
class StitchToneInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "stitch"
    instruction = (
        "### Tone\n"
        "- Use a warm, supportive, professional tone.\n"
        "- Be encouraging but specific; avoid vague praise."
    )
