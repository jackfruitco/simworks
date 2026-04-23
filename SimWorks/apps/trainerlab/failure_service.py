"""Centralised handling for TrainerLab simulation failure records and alerting.

This module is the single place that:
  1. Creates/updates a durable SimulationFailureRecord when a simulation fails.
  2. Sends an operational email alert to the errors inbox.

Both operations are best-effort: exceptions are caught and logged so that
a failure in this module never prevents the upstream failure path from completing.
"""

from __future__ import annotations

from config.logging import get_logger

logger = get_logger(__name__)

FAILURE_ALERT_RECIPIENT = "errors@jackfruitco.com"
LAB_SLUG = "trainerlab"


def _get_environment() -> str:
    from django.conf import settings

    return str(getattr(settings, "EMAIL_ENVIRONMENT_NAME", "unknown")).strip() or "unknown"


def record_simulation_failure(
    *,
    simulation,
    trainer_session=None,
    reason_code: str = "",
    reason_text: str = "",
    exception_class: str = "",
    exception_message: str = "",
    traceback_text: str = "",
    correlation_id: str = "",
    service_call_id: str = "",
    retryable: bool = True,
    metadata: dict | None = None,
) -> "SimulationFailureRecord":
    """Idempotent upsert of a SimulationFailureRecord keyed by simulation.

    The OneToOneField on simulation guarantees at most one record per simulation.
    Repeated calls update the existing record rather than creating duplicates.
    """
    from .models import SimulationFailureRecord

    environment = _get_environment()
    defaults = {
        "environment": environment,
        "lab_slug": LAB_SLUG,
        "trainer_session": trainer_session,
        "user_id": simulation.user_id,
        "account_id": simulation.account_id,
        "simulation_status": simulation.status,
        "session_status": getattr(trainer_session, "status", "") if trainer_session else "",
        "terminal_reason_code": reason_code or simulation.terminal_reason_code or "",
        "terminal_reason_text": reason_text or simulation.terminal_reason_text or "",
        "exception_class": exception_class,
        "exception_message": exception_message,
        "traceback_text": traceback_text,
        "correlation_id": correlation_id,
        "service_call_id": service_call_id,
        "retryable": retryable,
        "metadata_json": metadata or {},
    }
    record, _ = SimulationFailureRecord.objects.update_or_create(
        simulation=simulation,
        defaults=defaults,
    )
    return record


def send_failure_alert_email(failure_record) -> None:
    """Send an operational summary email to errors@jackfruitco.com.

    Production failures send immediately.  Staging failures include a [STAGING]
    prefix (applied automatically by the email service's staging support).
    This function is non-fatal: exceptions are logged and swallowed.
    """
    try:
        from apps.common.emailing.service import send_transactional_email
        from apps.common.emailing.environment import get_email_environment_label

        environment = failure_record.environment
        environment_label = get_email_environment_label(environment_hint=environment)
        is_staging = environment_label == "staging"
        staging_prefix = "[STAGING] " if is_staging else ""

        subject = (
            f"{staging_prefix}TrainerLab Simulation Failure — "
            f"sim#{failure_record.simulation_id} [{environment}]"
        )
        body_lines = [
            f"Environment:       {environment}",
            f"Lab:               {failure_record.lab_slug}",
            f"Simulation ID:     {failure_record.simulation_id}",
            f"Trainer Session:   {failure_record.trainer_session_id or 'N/A'}",
            f"User ID:           {failure_record.user_id or 'N/A'}",
            f"Account ID:        {failure_record.account_id or 'N/A'}",
            f"Terminal Code:     {failure_record.terminal_reason_code or 'N/A'}",
            f"Terminal Text:     {failure_record.terminal_reason_text or 'N/A'}",
            f"Exception:         {failure_record.exception_class or 'N/A'}"
            + (f": {failure_record.exception_message}" if failure_record.exception_message else ""),
            f"Correlation ID:    {failure_record.correlation_id or 'N/A'}",
            f"Service Call ID:   {failure_record.service_call_id or 'N/A'}",
            f"Retryable:         {failure_record.retryable}",
            "",
            "Archival policy: this simulation will be auto-archived after a 5-minute grace period.",
        ]
        text_body = "\n".join(body_lines)
        send_transactional_email(
            to=[FAILURE_ALERT_RECIPIENT],
            subject=subject,
            text_body=text_body,
            environment_hint=environment,
        )
    except Exception:
        logger.exception(
            "failure_service.email_alert_failed",
            simulation_id=failure_record.simulation_id,
        )


def handle_simulation_failure(
    *,
    simulation,
    trainer_session=None,
    reason_code: str = "",
    reason_text: str = "",
    exception_class: str = "",
    exception_message: str = "",
    traceback_text: str = "",
    correlation_id: str = "",
    service_call_id: str = "",
    retryable: bool = True,
    metadata: dict | None = None,
) -> None:
    """Convenience wrapper: record failure and send alert in one call."""
    try:
        record = record_simulation_failure(
            simulation=simulation,
            trainer_session=trainer_session,
            reason_code=reason_code,
            reason_text=reason_text,
            exception_class=exception_class,
            exception_message=exception_message,
            traceback_text=traceback_text,
            correlation_id=correlation_id,
            service_call_id=service_call_id,
            retryable=retryable,
            metadata=metadata,
        )
        send_failure_alert_email(record)
    except Exception:
        logger.exception(
            "failure_service.handle_simulation_failure_error",
            simulation_id=getattr(simulation, "pk", None),
        )
