"""Signal handlers for guard usage recording.

Hooks into ``orchestrai_django.signals.service_call_succeeded`` to
automatically record token usage at session / user / account level
whenever a ServiceCall completes.
"""

from __future__ import annotations

from config.logging import get_logger

from .policy import _detect_lab_type, _resolve_product_code

logger = get_logger(__name__)


def on_service_call_succeeded(sender, **kwargs):
    """Record usage when an Orca service call completes successfully."""
    call = kwargs.get("call")
    if call is None:
        return

    total_tokens = getattr(call, "total_tokens", 0) or 0
    if total_tokens == 0:
        return

    context = getattr(call, "context", None) or {}
    simulation_id = context.get("simulation_id")
    if not simulation_id:
        # Try related_object_id as fallback.
        simulation_id = getattr(call, "related_object_id", None)

    if not simulation_id:
        return

    try:
        simulation_id = int(simulation_id)
    except (TypeError, ValueError):
        return

    try:
        from apps.simcore.models import Simulation

        simulation = Simulation.objects.select_related("user", "account").get(
            pk=simulation_id,
        )
    except Exception:
        logger.debug(
            "guards.usage.simulation_not_found",
            simulation_id=simulation_id,
        )
        return

    lab_type = _detect_lab_type(simulation)
    product_code = _resolve_product_code(simulation, lab_type)

    from .services import record_usage

    record_usage(
        simulation_id=simulation_id,
        user_id=getattr(simulation.user, "pk", None),
        account_id=getattr(simulation.account, "pk", None),
        lab_type=lab_type,
        product_code=product_code,
        input_tokens=getattr(call, "input_tokens", 0) or 0,
        output_tokens=getattr(call, "output_tokens", 0) or 0,
        reasoning_tokens=getattr(call, "reasoning_tokens", 0) or 0,
        total_tokens=total_tokens,
    )


def _connect_signals():
    """Import-time signal connection using the actual signal object.

    Called by ``GuardsConfig.ready()`` to avoid import-order issues.
    """
    from orchestrai_django.signals import service_call_succeeded

    # Disconnect the string-based receiver and reconnect with the actual signal.
    service_call_succeeded.connect(
        on_service_call_succeeded,
        dispatch_uid="guards_record_usage_on_service_call",
    )
