# chatlab/views.py
import json
import logging

from asgiref.sync import sync_to_async
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from api.v1.sse import stream_outbox_events
from apps.chatlab.utils import (
    create_new_simulation,
    maybe_start_simulation,
)
from apps.common.decorators import resolve_user, simulation_required
from apps.common.models import OutboxEvent
from apps.common.outbox.outbox import order_outbox_queryset
from apps.common.retries import (
    has_user_retries_remaining,
    is_initial_generation_retryable_reason,
)
from apps.simcore.models import Simulation
from apps.simcore.tools import aget_tool, alist_tools
from orchestrai_django.models import ServiceCall

from .models import Message

logger = logging.getLogger(__name__)


@login_required
def index(request):
    simulations = (
        Simulation.objects.filter(user=request.user)
        if request.user.is_authenticated
        else Simulation.objects.none()
    )
    search_query = request.GET.get("q", "").strip()
    search_messages = request.GET.get("search_messages") == "1"

    # Set simulation query filters if provided search_query
    if search_query:
        from functools import reduce
        from operator import or_

        fields = ["diagnosis", "chief_complaint", "prompt"]

        # Add input field if search_messages is True
        if search_messages:
            fields.append("messages__content")

        qs = reduce(or_, (Q(**{f"{f}__icontains": search_query}) for f in fields))

        simulations = simulations.filter(qs).distinct()

    simulations = simulations.order_by("-start_timestamp")
    paginator = Paginator(simulations, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    template = (
        "chatlab/partials/simulation_history_list.html" if request.htmx else "chatlab/index.html"
    )
    return render(
        request,
        template,
        {
            "simulations": page_obj,
            "search_query": search_query,
            "search_messages": search_messages,
        },
    )


@login_required
@resolve_user
async def create_simulation(request):
    modifiers = request.GET.getlist("modifier")
    # Errors during AI service execution are handled via signal receivers
    simulation = await create_new_simulation(user=request.user, modifiers=modifiers)
    return await sync_to_async(redirect)("chatlab:run_simulation", simulation_id=simulation.id)


@login_required
@resolve_user
@simulation_required("simulation_id", owner_required=True)
async def run_simulation(request, simulation_id, included_tools="__ALL__"):
    try:
        simulation = await Simulation.objects.select_related("user").aget(id=simulation_id)
    except Simulation.DoesNotExist:
        return Http404("Simulation not found.")

    if simulation.user != request.user:
        return HttpResponseForbidden("Waaaaaait a minute. This isn't your simulation!")

    tools = []

    if included_tools == "__ALL__":
        # Load all registered tool classes
        for tool_class in await alist_tools():
            tool = tool_class(simulation)
            tool_data = await tool.ato_dict()
            tools.append(tool_data)
    elif not included_tools:
        tools = []
    else:
        for tool_name in included_tools.split(","):
            tool_class = await aget_tool(tool_name)
            if tool_class:
                tool = tool_class(simulation)
                tool_data = await tool.ato_dict()
                tools.append(tool_data)

    await maybe_start_simulation(simulation)

    logger.debug(f"Sim{simulation_id} requested tools: {included_tools} ")
    simulation_retryable = (
        simulation.status == Simulation.SimulationStatus.FAILED
        and is_initial_generation_retryable_reason(simulation.terminal_reason_code)
        and has_user_retries_remaining(simulation.initial_retry_count)
    )

    context = {
        "simulation": simulation,
        "tools": tools,
        "sim_start_unix": simulation.start_timestamp_ms or 0,
        "sim_end_unix": simulation.end_timestamp_ms or 0,
        "time_limit_ms": simulation.time_limit_ms or 0,
        "simulation_locked": simulation.is_complete,
        "simulation_status": simulation.status,
        "simulation_terminal_reason_code": simulation.terminal_reason_code,
        "simulation_terminal_reason_text": simulation.terminal_reason_text,
        "simulation_retryable": simulation_retryable,
    }

    return await sync_to_async(render)(request, "chatlab/simulation.html", context)


@require_GET
def get_metadata_checksum(request, simulation_id):
    """Return simulation metadata checksum."""
    simulation = get_object_or_404(Simulation, id=simulation_id)
    return JsonResponse({"checksum": simulation.metadata_checksum})


@require_GET
@login_required
def refresh_messages(request, simulation_id):
    get_object_or_404(Simulation, id=simulation_id, user=request.user)
    qs = Message.objects.filter(simulation_id=simulation_id)

    # Filter by conversation when specified (multi-conversation support)
    conversation_id = request.GET.get("conversation_id")
    if conversation_id:
        qs = qs.filter(conversation_id=conversation_id)

    msg_list = qs.order_by("-timestamp")[:5]
    msg_list = reversed(msg_list)  # Show oldest at top
    return render(request, "chatlab/partials/messages.html", {"messages": msg_list})


@require_GET
@login_required
def load_older_messages(request, simulation_id):
    get_object_or_404(Simulation, id=simulation_id, user=request.user)
    before_id = request.GET.get("before")
    try:
        before_message = Message.objects.get(id=before_id)
    except Message.DoesNotExist:
        return JsonResponse({"error": "Message not found."}, status=404)

    # Use a compound cursor so that messages sharing the same timestamp are
    # never skipped or repeated at a page boundary.
    qs = Message.objects.filter(simulation_id=simulation_id).filter(
        Q(timestamp__lt=before_message.timestamp)
        | Q(timestamp=before_message.timestamp, id__lt=before_message.id)
    )

    # Filter by conversation when specified (multi-conversation support)
    conversation_id = request.GET.get("conversation_id")
    if conversation_id:
        qs = qs.filter(conversation_id=conversation_id)

    msg_list = qs.order_by("-timestamp")[:5]
    msg_list = reversed(msg_list)
    return render(request, "chatlab/partials/messages.html", {"messages": msg_list})


@require_GET
@login_required
def modifier_selector(request):
    """Return modifier selector as HTMX partial.

    Returns server-rendered modifier checkboxes for the simulation
    creation form, replacing the previous GraphQL-based approach.
    """
    from apps.simcore.modifiers import get_modifier_groups

    # Get groups for chatlab (exclude Feedback group for now)
    groups = get_modifier_groups(["ClinicalScenario", "ClinicalDuration"])

    return render(
        request,
        "chatlab/partials/_modifier_selector.html",
        {"modifier_groups": groups},
    )


@require_POST
@login_required
def end_simulation(request, simulation_id):
    simulation = get_object_or_404(Simulation, id=simulation_id, user=request.user)
    if not simulation.end_timestamp:
        simulation.end()
    return redirect("chatlab:run_simulation", simulation_id=simulation.id)


@require_GET
@login_required
def get_single_message(request, simulation_id, message_id):
    """Return HTML for a single message (for HTMX append after WebSocket notification)."""
    get_object_or_404(Simulation, id=simulation_id, user=request.user)
    try:
        message = (
            Message.objects.select_related("sender")
            .prefetch_related("media")
            .get(
                id=message_id,
                simulation_id=simulation_id,
            )
        )
    except Message.DoesNotExist:
        return HttpResponse("", status=404)

    return render(
        request,
        "chatlab/partials/_message.html",
        {
            "message": message,
            "user": request.user,
        },
    )


# ---------------------------------------------------------------------------
# Admin watch views
# ---------------------------------------------------------------------------


@staff_member_required
def watch_simulation(request, simulation_id):
    """Admin-only live event watch view for a simulation."""
    from django.core.serializers.json import DjangoJSONEncoder

    logger.info(
        "watch_simulation: admin=%s viewing sim=%s",
        request.user.pk,
        simulation_id,
    )
    simulation = get_object_or_404(Simulation, id=simulation_id)
    outbox_qs = order_outbox_queryset(OutboxEvent.objects.filter(simulation_id=simulation_id))
    service_calls = ServiceCall.objects.for_simulation(simulation_id).order_by("created_at")

    # Pre-serialize outbox events to valid JSON for the Alpine.js component
    outbox_events_json = json.dumps(
        [
            {
                "event_id": str(ev.id),
                "event_type": ev.event_type,
                "created_at": ev.created_at.isoformat(),
                "correlation_id": ev.correlation_id or "",
                "payload": ev.payload,
                "status": ev.status,
                "delivery_attempts": ev.delivery_attempts,
                "last_error": ev.last_error,
                "idempotency_key": ev.idempotency_key,
                "expanded": False,
            }
            for ev in outbox_qs
        ],
        cls=DjangoJSONEncoder,
    )

    return render(
        request,
        "simulation_watch.html",
        {
            "simulation": simulation,
            "outbox_events_json": outbox_events_json,
            "service_calls": service_calls,
            "stream_url": reverse("chatlab:watch_stream", args=[simulation_id]),
            "service_calls_url": reverse("chatlab:watch_service_calls", args=[simulation_id]),
            "back_url": reverse("chatlab:run_simulation", args=[simulation_id]),
            "lab_name": "ChatLab",
        },
    )


@staff_member_required
def watch_stream(request, simulation_id):
    """SSE stream for the admin watch view (session-cookie auth)."""
    logger.debug(
        "watch_stream: SSE opened admin=%s sim=%s cursor=%s",
        request.user.pk,
        simulation_id,
        request.GET.get("cursor"),
    )
    get_object_or_404(Simulation, id=simulation_id)
    cursor = request.GET.get("cursor") or None
    event_type_prefix = request.GET.get("event_prefix") or None
    return stream_outbox_events(
        simulation_id=simulation_id,
        cursor=cursor,
        event_type_prefix=event_type_prefix,
        heartbeat_interval_seconds=10.0,
    )


@staff_member_required
def watch_service_calls(request, simulation_id):
    """HTMX partial — refreshes service call table on the watch page."""
    logger.debug(
        "watch_service_calls: admin=%s sim=%s",
        request.user.pk,
        simulation_id,
    )
    get_object_or_404(Simulation, id=simulation_id)
    service_calls = ServiceCall.objects.for_simulation(simulation_id).order_by("created_at")
    return render(
        request,
        "partials/watch_service_calls.html",
        {
            "service_calls": service_calls,
            "service_calls_url": reverse("chatlab:watch_service_calls", args=[simulation_id]),
        },
    )
