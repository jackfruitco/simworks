# trainerlab/orca/services/vitals.py
"""
Service class to generate vital sign progression for the TrainerLab application.

This service handles only physiological measurements — it does not modify conditions
or interventions. It is designed to run independently of the full runtime turn service,
enabling higher-cadence or on-demand vital sign updates.
"""

from asgiref.sync import sync_to_async

from apps.trainerlab.services import apply_vitals_progression_output, clear_runtime_processing
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

from ..instructions.vitals import (
    VitalsProgressionContextInstruction,
    VitalsProgressionContractInstruction,
    VitalsProgressionRoleInstruction,
)


@orca.service
class GenerateVitalsProgression(
    VitalsProgressionRoleInstruction,
    VitalsProgressionContractInstruction,
    VitalsProgressionContextInstruction,
    DjangoBaseService,
):
    """
    Generate a focused vital sign progression update for the current patient state.

    Unlike GenerateTrainerRuntimeTurn, this service only reads conditions/interventions
    as context and outputs updated vital sign ranges. It is safe to call in parallel with
    or independently of the full runtime turn.

    Identity: services.trainerlab.vitals.GenerateVitalsProgression
    """

    required_context_keys = ("simulation_id", "session_id")
    use_native_output = True

    from ..schemas.vitals import VitalsProgressionOutput as _Schema

    response_schema = _Schema

    async def on_success_ctx(self, *, context, result) -> None:
        output = result.output
        payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        await sync_to_async(apply_vitals_progression_output, thread_sensitive=True)(
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
            requeue_current_batch=False,
        )
