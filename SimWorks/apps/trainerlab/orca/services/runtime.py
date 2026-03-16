# trainerlab/orca/services/runtime.py
"""
Service class to generate runtime turns for the TrainerLab application.
"""

from typing import ClassVar

from asgiref.sync import sync_to_async

from apps.trainerlab.services import apply_runtime_turn_output, clear_runtime_processing
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca


@orca.service
class GenerateTrainerRuntimeTurn(PreviousResponseMixin, DjangoBaseService):
    instruction_refs: ClassVar[list[str]] = [
        "trainerlab.initial.TrainerLabMixin",
        "trainerlab.runtime.TrainerRuntimeRoleInstruction",
        "trainerlab.runtime.TrainerRuntimeContractInstruction",
        "trainerlab.runtime.TrainerRuntimeContextInstruction",
    ]
    required_context_keys = ("simulation_id", "session_id")
    use_native_output = True

    from ..schemas import TrainerRuntimeTurnOutput as _Schema

    response_schema = _Schema

    async def on_success_ctx(self, *, context, result) -> None:
        output = result.output
        payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        await sync_to_async(apply_runtime_turn_output, thread_sensitive=True)(
            session_id=context["session_id"],
            output_payload=payload,
            service_context=context,
        )

    async def on_failure_ctx(self, *, context, err: Exception) -> None:
        session_id = context.get("session_id")
        if session_id is None:
            return
        await sync_to_async(clear_runtime_processing, thread_sensitive=True)(
            session_id=session_id,
            error=str(err),
            requeue_current_batch=True,
        )
