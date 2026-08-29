# trainerlab/orca/instructions/runtime.py
"""Dynamic instruction classes for TrainerLab runtime turn service.

Static instructions (TrainerRuntimeRoleInstruction, TrainerRuntimeContractInstruction)
are defined in runtime.yaml (same directory).
"""

from apps.trainerlab.runtime_llm import render_runtime_llm_context
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=40)
class TrainerRuntimeContextInstruction(NsMixin, BaseInstruction):
    group = "runtime"

    def render_instruction(self) -> str:
        runtime_llm_context = render_runtime_llm_context(
            self.context.get("runtime_llm_context", {})
        )
        elapsed = self.context.get("active_elapsed_seconds", 0)
        return (
            "Current authoritative runtime context:\n"
            f"- Active elapsed seconds: {elapsed}\n"
            f"- Runtime LLM context JSON: {runtime_llm_context}\n"
            "Treat this compact context as the source of truth for the current turn. "
            "It already reflects the authoritative backend state projection for active causes, "
            "problems, vitals, pulses, interventions, and pending runtime reasons. "
            "Treat `interventions` as the only performed actions. Never create or update causes "
            "directly. Recommend observations and suggestions only; the deterministic engine will "
            "decide what actually persists. Never imply that care was performed unless it already "
            "exists in the input context. Instructor intent should help an instructor anticipate "
            "what the engine is likely to do next."
        )
