# trainerlab/orca/services/runtime.py
"""
Service class to generate runtime turns for the TrainerLab application.

This service handles the logic for generating runtime turns within the TrainerLab
environment by utilizing various mixins and runtime-related instructions. It manages
the process of processing runtime outputs on success and clearing runtime state on
failure. The service is integrated with orchestration through the `orca.service` decorator.

Attributes:
    required_context_keys (tuple[str]): The keys required in the context for the service
        to operate correctly. Includes `simulation_id` and `session_id`.
    use_native_output (bool): Indicates if the service will use native output processing.
    response_schema (TrainerRuntimeTurnOutput): The schema used for validating the
        response structure of the service.
"""

from asgiref.sync import sync_to_async

from apps.trainerlab.services import apply_runtime_turn_output, clear_runtime_processing
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca

from ..instructions import (
    TrainerLabMixin,
    TrainerRuntimeContextInstruction,
    TrainerRuntimeContractInstruction,
    TrainerRuntimeRoleInstruction,
)


@orca.service
class GenerateTrainerRuntimeTurn(
    PreviousResponseMixin,
    TrainerLabMixin,
    TrainerRuntimeRoleInstruction,
    TrainerRuntimeContractInstruction,
    TrainerRuntimeContextInstruction,
    DjangoBaseService,
):
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
