# trainerlab/orca/services/debrief.py

from __future__ import annotations

from typing import ClassVar

from asgiref.sync import sync_to_async

from apps.trainerlab.debrief import fail_debrief
from apps.trainerlab.services import apply_debrief_output
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.service
class GenerateTrainerRunDebrief(DjangoBaseService):
    instruction_refs: ClassVar[list[str]] = [
        "trainerlab.debrief.TrainerDebriefRoleInstruction",
        "trainerlab.debrief.TrainerDebriefContractInstruction",
        "trainerlab.debrief.TrainerDebriefContextInstruction",
    ]
    required_context_keys = (
        "simulation_id",
        "session_id",
        "debrief_generation",
        "evidence_revision",
        "evidence",
    )
    use_native_output = True

    from ..schemas import TrainerRunDebriefOutput as _Schema

    response_schema = _Schema

    async def _aprepare_context(self) -> None:
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        # The reservation includes an immutable evidence snapshot. Never reload a
        # newer summary into an older generation or send raw commands to the model.

    async def on_success_ctx(self, *, context, result) -> None:
        output = result.output
        payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        await sync_to_async(apply_debrief_output, thread_sensitive=True)(
            session_id=context["session_id"],
            output_payload=payload,
            correlation_id=context.get("correlation_id"),
            service_context=context,
        )

    async def on_failure_ctx(self, *, context, err: Exception) -> None:
        await sync_to_async(fail_debrief, thread_sensitive=True)(
            session_id=context["session_id"],
            context=context,
        )
