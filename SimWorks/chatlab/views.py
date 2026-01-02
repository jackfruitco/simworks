# chatlab/views.py
import logging

from asgiref.sync import sync_to_async
from chatlab.utils import (
    create_new_simulation,
    maybe_start_simulation,
)
from core.decorators import resolve_user, simulation_required
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET
from simulation.models import Simulation
from simulation.tools import aget_tool, alist_tools

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
        "chatlab/partials/simulation_history_list.html"
        if request.htmx
        else "chatlab/index.html"
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
    return await sync_to_async(redirect)(
        "chatlab:run_simulation", simulation_id=simulation.id
    )


@login_required
@resolve_user
@simulation_required("simulation_id", owner_required=True)
async def run_simulation(request, simulation_id, included_tools="__ALL__"):
    try:
        simulation = await Simulation.objects.select_related("user").aget(
            id=simulation_id
        )
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

    context = {
        "simulation": simulation,
        "tools": tools,
        "sim_start_unix": simulation.start_timestamp_ms or 0,
        "sim_end_unix": simulation.end_timestamp_ms or 0,
        "time_limit_ms": simulation.time_limit_ms or 0,
        "simulation_locked": simulation.is_complete,
    }

    # Checks for feedback continuation -
    #   If a simulation has ended, but the user requests to continue feedback discussion,
    #   a request will be made to run_simulation with feedback_continue_conversation=True
    #   This will override the simulation lock to allow user's to type in the chat window.
    val = request.GET.get("feedback_continue_conversation", "").lower()
    feedback_continuation = val in ("true", "1", "yes", "on")

    if feedback_continuation:
        context["simulation_locked"] = False
        context["feedback_continuation"] = True

        logger.debug(
            "Simulation pk=%s: user requesting feedback continuation. "
            "Overriding context (simulation_locked=%s, feedback_continuation=%s)",
            simulation_id, context["simulation_locked"], context["feedback_continuation"],
        )

    return await sync_to_async(render)(request, "chatlab/simulation.html", context)


@require_GET
def get_metadata_checksum(request, simulation_id):
    """Return simulation metadata checksum."""
    simulation = get_object_or_404(Simulation, id=simulation_id)
    return JsonResponse({"checksum": simulation.metadata_checksum})


@require_GET
def refresh_messages(request, simulation_id):
    messages = Message.objects.filter(simulation_id=simulation_id).order_by(
        "-timestamp"
    )[:5]
    messages = reversed(messages)  # Show oldest at top
    return render(request, "chatlab/partials/messages.html", {"messages": messages})


@require_GET
def load_older_messages(request, simulation_id):
    before_id = request.GET.get("before")
    try:
        before_message = Message.objects.get(id=before_id)
    except Message.DoesNotExist:
        return JsonResponse({"error": "Message not found."}, status=404)

    messages = Message.objects.filter(
        simulation_id=simulation_id, timestamp__lt=before_message.timestamp
    ).order_by("-timestamp")[:5]
    messages = reversed(messages)
    return render(request, "chatlab/partials/messages.html", {"messages": messages})


from django.views.decorators.http import require_POST


@require_POST
@login_required
def end_simulation(request, simulation_id):
    simulation = get_object_or_404(Simulation, id=simulation_id, user=request.user)
    if not simulation.end_timestamp:
        simulation.end()
    return redirect("chatlab:run_simulation", simulation_id=simulation.id)
