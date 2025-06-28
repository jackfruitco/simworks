# chatlab/views.py
import logging

from asgiref.sync import async_to_sync
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from chatlab.utils import create_new_simulation
from chatlab.utils import maybe_start_simulation
from core.decorators import resolve_user
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django.shortcuts import aget_object_or_404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_GET
from simcore.models import Simulation
from simcore.tools import aget_tool
from simcore.tools import alist_tools

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

    if search_query:
        if search_messages:
            simulations = simulations.filter(
                message__content__icontains=search_query
            ).distinct()
        else:
            simulations = simulations.filter(description__icontains=search_query)

    simulations = simulations.order_by("-start_timestamp")
    paginator = Paginator(simulations, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    template = (
        "chatlab/partials/simulation_history.html"
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
    simulation = await create_new_simulation(user=request.user, modifiers=modifiers)
    return await sync_to_async(redirect)(
        "chatlab:run_simulation", simulation_id=simulation.id
    )


@login_required
@resolve_user
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
