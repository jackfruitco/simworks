"""Shared lab-order submission helpers for API v1 endpoints."""

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from ninja.errors import HttpError

from api.v1.schemas.lab_orders import LabOrdersOut
from api.v1.utils import get_chatlab_simulation_for_user
from apps.chatlab.access import require_lab_access as require_chatlab_access
from config.logging import get_logger

logger = get_logger(__name__)


def submit_lab_orders_request(
    request: HttpRequest,
    simulation_id: int,
    raw_orders: list[str],
) -> LabOrdersOut:
    """Validate, normalize, and enqueue lab-order generation."""
    from apps.chatlab.orca.services.lab_orders import GenerateLabResults
    from apps.simcore.models import Simulation

    require_chatlab_access(request.auth, request=request)

    simulation = get_chatlab_simulation_for_user(simulation_id, request.auth, request=request)
    if simulation.status != Simulation.SimulationStatus.IN_PROGRESS:
        raise HttpError(400, "Lab orders can only be submitted for in-progress simulations")

    orders = list(dict.fromkeys(order.strip() for order in raw_orders if order.strip()))
    if not orders:
        raise HttpError(400, "orders must contain at least one non-empty item")

    async def _enqueue():
        return await GenerateLabResults.task.using(
            context={
                "simulation_id": simulation.id,
                "orders": orders,
            }
        ).aenqueue()

    try:
        call_id = async_to_sync(_enqueue)()
        logger.info(
            "lab_orders.enqueued",
            simulation_id=simulation_id,
            order_count=len(orders),
            call_id=call_id,
        )
    except Exception as exc:
        logger.exception(
            "lab_orders.enqueue_failed",
            simulation_id=simulation_id,
            order_count=len(orders),
        )
        raise HttpError(500, "Failed to enqueue lab order processing. Please try again.") from exc

    return LabOrdersOut(status="accepted", call_id=call_id, orders=orders)
