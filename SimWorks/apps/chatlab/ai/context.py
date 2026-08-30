"""Canonical patient runtime context shared by text and voice runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from asgiref.sync import sync_to_async

from apps.simcore.models import Conversation, Simulation


@dataclass(frozen=True)
class PatientRuntimeContext:
    simulation_id: int
    conversation_id: int
    patient_name: str
    patient_full_name: str
    chief_complaint: str
    conversation_name: str
    persona: str
    modifier_prompt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _modifier_prompt(simulation: Simulation) -> str:
    snapshot = getattr(simulation, "modifier_snapshot", None) or []
    if snapshot:
        from apps.simcore.modifiers import render_modifier_prompt_from_snapshot

        return render_modifier_prompt_from_snapshot(snapshot) or ""

    modifiers = getattr(simulation, "modifiers", None) or []
    if not modifiers:
        return ""
    from apps.simcore.modifiers import render_modifier_prompt

    return render_modifier_prompt("chatlab", modifiers) or ""


def build_patient_runtime_context_sync(
    *, simulation: Simulation, conversation: Conversation
) -> PatientRuntimeContext:
    patient_full_name = " ".join((simulation.sim_patient_full_name or "the patient").split())
    return PatientRuntimeContext(
        simulation_id=simulation.pk,
        conversation_id=conversation.pk,
        patient_name=simulation.sim_patient_display_name or patient_full_name,
        patient_full_name=patient_full_name,
        chief_complaint=simulation.chief_complaint or "the presenting concern",
        conversation_name=conversation.display_name or conversation.conversation_type.display_name,
        persona=getattr(conversation.conversation_type, "ai_persona", "") or "patient",
        modifier_prompt=_modifier_prompt(simulation),
    )


async def build_patient_runtime_context(
    *,
    simulation: Simulation | None = None,
    conversation: Conversation | None = None,
    simulation_id: int | None = None,
    conversation_id: int | None = None,
) -> PatientRuntimeContext:
    """Load and normalize one patient context for any supported modality."""

    if simulation is None:
        if simulation_id is None:
            raise ValueError("simulation or simulation_id is required")
        simulation = await Simulation.objects.aget(pk=simulation_id)
    if conversation is None:
        if conversation_id is None:
            conversation = await Conversation.objects.select_related("conversation_type").aget(
                simulation_id=simulation.pk,
                conversation_type__slug="simulated_patient",
            )
        else:
            conversation = await Conversation.objects.select_related("conversation_type").aget(
                pk=conversation_id,
                simulation_id=simulation.pk,
            )

    # Modifier fallback can use synchronous catalog helpers; keep it outside
    # the async ORM path while retaining the same canonical builder.
    return await sync_to_async(build_patient_runtime_context_sync)(
        simulation=simulation,
        conversation=conversation,
    )
