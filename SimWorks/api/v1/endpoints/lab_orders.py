"""Lab orders endpoint for API v1.

Allows users to submit signed lab orders and trigger AI result generation.
"""

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.lab_orders import LabOrdersOut, LabOrderSubmit
from api.v1.utils import get_simulation_for_user
from apps.common.ratelimit import api_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["lab-orders"], auth=DualAuth())


@router.post(
    "/{simulation_id}/lab-orders/",
    response={202: LabOrdersOut},
    summary="Submit signed lab orders",
    description=(
        "Submits a list of signed lab orders to the AI engine. "
        "The AI generates clinically plausible results for each ordered test based on the "
        "patient's presentation. Results are persisted as structured metadata and broadcast "
        "to connected clients via durable `simulation.metadata.results_created` events "
        "(with temporary `metadata.created` compatibility aliases). "
        "Returns 202 Accepted immediately; results arrive asynchronously."
    ),
)
@api_rate_limit
def submit_lab_orders(
    request: HttpRequest,
    simulation_id: int,
    body: LabOrderSubmit,
) -> tuple[int, LabOrdersOut]:
    """Submit signed lab orders and enqueue AI result generation."""
    from apps.chatlab.orca.services.lab_orders import GenerateLabResults
    from apps.simcore.models import Simulation

    user = request.auth
    simulation = get_simulation_for_user(simulation_id, user)

    if simulation.status != Simulation.Status.IN_PROGRESS:
        raise HttpError(400, "Lab orders can only be submitted for in-progress simulations")

    # Deduplicate and normalise order strings
    orders = list(dict.fromkeys(o.strip() for o in body.orders if o.strip()))
    if not orders:
        raise HttpError(400, "orders must contain at least one non-empty item")

    async def _enqueue():
        return await GenerateLabResults.task.using(
            context={
                "simulation_id": simulation.id,
                "orders": orders,
            }
        ).aenqueue()

    call_id: str | None = None
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

    return 202, LabOrdersOut(status="accepted", call_id=call_id, orders=orders)
