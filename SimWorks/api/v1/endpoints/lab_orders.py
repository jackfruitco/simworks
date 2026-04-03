"""Lab orders endpoint for API v1.

Allows users to submit signed lab orders and trigger AI result generation.
"""

from django.http import HttpRequest
from ninja import Router

from api.v1.auth import DualAuth
from api.v1.endpoints._lab_order_submission import submit_lab_orders_request
from api.v1.schemas.lab_orders import LabOrdersOut, LabOrderSubmit
from apps.common.ratelimit import api_rate_limit

router = Router(tags=["lab-orders"], auth=DualAuth())


@router.post(
    "/{simulation_id}/lab-orders/",
    response={202: LabOrdersOut},
    summary="Submit signed lab orders",
    description=(
        "Submits a list of signed lab orders to the AI engine. "
        "The AI generates clinically plausible results for each ordered test based on the "
        "patient's presentation. Results are persisted as structured metadata and broadcast "
        "to connected WebSocket clients via `patient.metadata.created` events. "
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
    return 202, submit_lab_orders_request(request, simulation_id, body.orders)
