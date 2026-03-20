from __future__ import annotations

from django.dispatch import receiver

from config.logging import get_logger
from orchestrai_django.models import CallStatus, ServiceCall
from orchestrai_django.signals import ai_response_failed, service_call_succeeded

from .services import (
    complete_initial_scenario_generation,
    fail_initial_scenario_generation,
)

logger = get_logger(__name__)


def _is_initial_generation_service(service_identity: str | None) -> bool:
    return "GenerateInitialScenario" in (service_identity or "")


@receiver(service_call_succeeded)
def handle_initial_generation_succeeded(
    sender,
    *,
    call=None,
    call_id=None,
    service_identity: str | None = None,
    context: dict | None = None,
    **kwargs,
) -> None:
    if not _is_initial_generation_service(service_identity):
        return

    service_call = call
    if service_call is None and call_id:
        try:
            service_call = ServiceCall.objects.only("domain_persisted", "context").get(pk=call_id)
        except ServiceCall.DoesNotExist:
            service_call = None

    if service_call is not None and not service_call.domain_persisted:
        logger.info("TrainerLab initial generation success deferred until persistence completes")
        return

    simulation_id = (context or {}).get("simulation_id")
    if not simulation_id:
        logger.warning("TrainerLab initial generation succeeded without simulation_id")
        return

    complete_initial_scenario_generation(
        simulation_id=int(simulation_id),
        correlation_id=(context or {}).get("correlation_id"),
        call_id=str(call_id) if call_id else None,
    )


@receiver(ai_response_failed)
def handle_initial_generation_failed(
    sender,
    *,
    call_id=None,
    error: str = "",
    context: dict | None = None,
    reason_code: str | None = None,
    user_retryable: bool | None = None,
    **kwargs,
) -> None:
    service_identity = ""
    call_context = dict(context or {})
    if call_id:
        try:
            call = ServiceCall.objects.only("service_identity", "status", "context").get(pk=call_id)
        except ServiceCall.DoesNotExist:
            logger.warning("TrainerLab failure handler could not resolve service call %s", call_id)
            call = None
        if call is not None:
            if call.status != CallStatus.FAILED:
                logger.info(
                    "Ignoring non-terminal TrainerLab ai_response_failed",
                    extra={"call_id": call_id, "status": call.status},
                )
                return
            service_identity = call.service_identity or ""
            call_context.update(call.context or {})

    if not _is_initial_generation_service(service_identity):
        return

    simulation_id = call_context.get("simulation_id")
    if not simulation_id:
        logger.warning("TrainerLab initial generation failed without simulation_id")
        return

    fail_initial_scenario_generation(
        simulation_id=int(simulation_id),
        reason_code=reason_code,
        reason_text=error or "Initial scenario generation failed. Please try again.",
        retryable=bool(user_retryable) if user_retryable is not None else True,
        correlation_id=call_context.get("correlation_id"),
    )
