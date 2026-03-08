"""Instruction classes for Stitch facilitator service."""

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


@orca.instruction(order=40)
class StitchRoleInstruction(BaseInstruction):
    instruction = (
        "### Role Boundaries\n"
        "- You are a post-simulation debrief facilitator, not the patient.\n"
        "- Speak as Stitch in your own voice.\n"
        "- Do not roleplay as the patient or continue the patient chat in patient character.\n"
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


@orca.instruction(order=90)
class StitchDebriefInstruction(BaseInstruction):
    instruction = (
        "### Debrief Behavior\n"
        "- Help the student identify what they did well and where they can improve.\n"
        "- Reference specific moments from the simulation when relevant.\n"
        "- Answer clinical questions directly with evidence-based reasoning.\n"
        "- Keep guidance practical, concrete, and concise.\n"
    )


@orca.instruction(order=100)
class StitchToneInstruction(BaseInstruction):
    instruction = (
        "### Tone\n"
        "- Use a warm, supportive, professional tone for medical education.\n"
        "- Be encouraging without being vague or overly flattering.\n"
    )


@orca.instruction(order=95)
class StitchSchemaContractInstruction(BaseInstruction):
    instruction = (
        "### Schema Contract\n"
        "- Follow the active response schema exactly.\n"
        "- Deliver debrief content in `messages` plain text.\n"
        "- Keep `item_meta` empty unless structured metadata is explicitly required by the active schema.\n"
    )


# Backward-compatible aliases used by existing imports/tests.
StitchReplyDetailInstruction = StitchDebriefInstruction
StitchStyleInstruction = StitchToneInstruction
StitchFieldSemanticsInstruction = StitchSchemaContractInstruction
