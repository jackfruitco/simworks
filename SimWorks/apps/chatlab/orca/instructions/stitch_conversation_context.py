from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=50)
class StitchConversationContextInstruction(BaseInstruction):
    """Dynamic instruction that provides Stitch with patient conversation history."""

    required_context_keys = frozenset({"simulation_id"})

    async def render_instruction(self) -> str | None:
        from asgiref.sync import sync_to_async
        from django.core.exceptions import ObjectDoesNotExist
        from apps.simcore.models import Simulation

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
