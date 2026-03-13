"""Tool endpoints for API v1.

Provides JSON tool payloads and tool actions for native clients.
"""

from asgiref.sync import async_to_sync
from django.http import HttpRequest
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.tools import SignOrdersIn, SignOrdersOut, ToolListResponse, ToolOut
from api.v1.utils import get_simulation_for_user
from apps.common.ratelimit import api_rate_limit

router = Router(tags=["tools"], auth=DualAuth())


def _resolve_tool_or_404(tool_name: str):
    from apps.simcore.tools import get_tool

    tool_class = get_tool(tool_name)
    if not tool_class:
        raise HttpError(404, f"Tool not found: {tool_name}")
    return tool_class


@router.get(
    "/{simulation_id}/tools/",
    response=ToolListResponse,
    summary="List simulation tools",
    description="Returns JSON payloads for simulation tools.",
)
@api_rate_limit
def list_simulation_tools(
    request: HttpRequest,
    simulation_id: int,
    names: list[str] | None = Query(
        default=None,
        description="Optional repeated tool names filter (e.g., ?names=patient_history&names=patient_results)",
    ),
) -> ToolListResponse:
    from apps.simcore.tools import list_tools

    user = request.auth
    simulation = get_simulation_for_user(simulation_id, user)

    if names:
        tool_names = [name.lower() for name in names]
    else:
        tool_names = [tool_cls.tool_name.lower() for tool_cls in list_tools()]

    items: list[ToolOut] = []
    for name in tool_names:
        tool_class = _resolve_tool_or_404(name)
        payload = tool_class(simulation).to_dict()
        items.append(ToolOut(**payload))

    return ToolListResponse(items=items)


@router.get(
    "/{simulation_id}/tools/{tool_name}/",
    response=ToolOut,
    summary="Get a simulation tool",
    description="Returns JSON payload for a specific simulation tool.",
)
@api_rate_limit
def get_simulation_tool(
    request: HttpRequest,
    simulation_id: int,
    tool_name: str,
) -> ToolOut:
    user = request.auth
    simulation = get_simulation_for_user(simulation_id, user)
    tool_class = _resolve_tool_or_404(tool_name)
    return ToolOut(**tool_class(simulation).to_dict())


@router.post(
    "/{simulation_id}/tools/patient_results/orders/",
    response=SignOrdersOut,
    summary="Sign lab orders",
    description="Signs requested lab orders and enqueues feedback generation.",
)
@api_rate_limit
def sign_lab_orders(
    request: HttpRequest,
    simulation_id: int,
    body: SignOrdersIn,
) -> SignOrdersOut:
    from apps.simcore.orca.services import GenerateInitialFeedback

    if not body.submitted_orders:
        raise HttpError(400, "submitted_orders must include at least one item")

    user = request.auth
    simulation = get_simulation_for_user(simulation_id, user)

    async def _enqueue():
        return await GenerateInitialFeedback.task.using(
            context={
                "simulation_id": simulation.id,
                "lab_orders": body.submitted_orders,
            }
        ).aenqueue()

    async_to_sync(_enqueue)()
    return SignOrdersOut(status="ok", orders=body.submitted_orders)
