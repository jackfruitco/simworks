# chatlab/orca/services/stitch.py
"""
Stitch AI facilitator service for ChatLab.

Stitch is a friendly AI medical education facilitator that helps students
reflect on their simulation performance after the simulation ends.
Stitch has full context of the patient conversation and simulation metadata.
"""

import logging
from typing import ClassVar

from django.core.exceptions import ObjectDoesNotExist

from orchestrai.prompts import system_prompt
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import service
from apps.simcore.models import Simulation

logger = logging.getLogger(__name__)


@service
class GenerateStitchReply(
    PreviousResponseMixin,
    DjangoBaseService,
):
    """Generate a reply from Stitch, the AI facilitator.

    Stitch helps students debrief after a simulation — answering clinical
    questions, providing educational context, and encouraging reflection.

    Identity: services.chatlab.stitch.GenerateStitchReply
    """

    required_context_keys: ClassVar[tuple[str, ...]] = (
        "simulation_id",
        "conversation_id",
    )
    use_native_output = True

    from apps.chatlab.orca.schemas.stitch import StitchReplyOutputSchema as _Schema
    response_schema = _Schema

    async def _aprepare_context(self) -> None:
        """Populate user_message from stored user message ID."""
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        if self.context.get("user_message") is not None:
            return

        user_msg_id = self.context.get("user_msg") or self.context.get("user_msg_id")
        if not user_msg_id:
            return

        try:
            from apps.chatlab.models import Message
            msg = await Message.objects.aget(pk=user_msg_id)
        except Exception as exc:
            logger.warning("Unable to load user message %s: %s", user_msg_id, exc)
            return

        self.context["user_message"] = msg.content

    @system_prompt(weight=100)
    async def stitch_persona(self) -> str:
        """Core Stitch persona and simulation context."""
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

    @system_prompt(weight=50)
    async def simulation_context(self) -> str:
        """Provide Stitch with the patient conversation history for context."""
        from asgiref.sync import sync_to_async

        simulation_id = self.context.get("simulation_id")
        try:
            sim = await Simulation.objects.aget(pk=simulation_id)
        except (TypeError, ValueError, ObjectDoesNotExist):
            return ""

        history = await sync_to_async(sim.history)()
        if not history:
            return ""

        # Last 20 entries for context window efficiency
        lines = []
        for entry in history[-20:]:
            role = entry.get("role", "?")
            content = entry.get("content", "")
            lines.append(f"[{role}]: {content}")

        return "### Simulation Conversation History\n" + "\n".join(lines)

    @system_prompt(weight=10)
    def reply_instructions(self) -> str:
        """Instructions for generating Stitch replies."""
        return (
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
