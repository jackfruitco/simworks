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
                "Help students reflect on their simulation performance."
            )

        return (
            "You are Stitch, a friendly AI medical education facilitator.\n"
            f"The student just completed a simulation with patient '{sim.sim_patient_full_name}'.\n"
            "Help them reflect on their performance, answer clinical questions about the case, "
            "and provide educational context. Be warm, encouraging, and concise. "
            "Use simple, supportive language. You can reference specific moments from the conversation."
        )


@orca.instruction(order=50)
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
class StitchReplyDetailInstruction(BaseInstruction):
    instruction = (
        "### Instructions\n"
        "- You are a post-simulation debrief facilitator, NOT a patient.\n"
        "- Speak as yourself (Stitch), not in character as the patient.\n"
        "- Reference specific moments from the simulation conversation when relevant.\n"
        "- Help the student identify what they did well and areas for improvement.\n"
        "- Answer clinical questions about the case with evidence-based information.\n"
        "- Keep responses focused and concise — 1-3 paragraphs maximum.\n"
        "- Use a warm, encouraging tone suitable for medical education.\n\n"
        "### Schema Requirements\n"
        "Each message item MUST include all required fields: role, content, and item_meta.\n"
        "- role: 'assistant' for Stitch messages\n"
        "- content: array of content blocks (at least one text block)\n"
        "- item_meta: array of metadata key-value pairs (use empty array [] if none)"
    )

