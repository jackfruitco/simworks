# chatlab/views.py

import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden, HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_GET

from chatlab.utils import create_new_simulation, maybe_start_simulation
from simcore.models import Simulation
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
def create_simulation(request):
    sim = create_new_simulation(request.user)
    return redirect("chatlab:run_simulation", simulation_id=sim.id)


@login_required
def run_simulation(request, simulation_id):
    simulation = get_object_or_404(Simulation, id=simulation_id)

    if simulation.user != request.user:
        return HttpResponseForbidden("Waaaaaait a minute. This isn't your simulation!")

    maybe_start_simulation(simulation)

    simulation_metadata = simulation.metadata.exclude(attribute="feedback").exclude(attribute="patient history")
    feedback = simulation.metadata.filter(attribute="feedback")
    patient_metadata = simulation.formatted_patient_history

    context = {
        "simulation": simulation,
        "simulation_metadata": simulation_metadata,
        "patient_metadata": patient_metadata,
        "sim_start_unix": int(simulation.start_timestamp.timestamp() * 1000),
        "simulation_locked": simulation.is_complete,
        "feedback": feedback,
    }

    return render(request, "chatlab/simulation.html", context)

@require_GET
def get_metadata_checksum(request, simulation_id):
    """Return simulation metadata checksum."""
    simulation = get_object_or_404(Simulation, id=simulation_id)
    return JsonResponse({"checksum": simulation.metadata_checksum})

@require_GET
def refresh_simulation_metadata(request, simulation_id):
    """
    Return simulation metadata.

    :param request:
    :param simulation_id:
    :return:
    """
    simulation = get_object_or_404(Simulation, id=simulation_id)
    metadata = simulation.metadata.exclude(attribute="patient history").exclude(attribute="feedback")
    logger.debug(f"[Sim#{simulation.pk}] refreshed simulation metadata: {metadata}")
    return render(
        request,
        "chatlab/partials/_metadata_simulation_inner.html",
        context={"simulation_metadata": metadata}
    )

@require_GET
def refresh_patient_metadata(request, simulation_id):
    """
    Return patient history metadata.
    :param request:
    :param simulation_id:
    :return:
    """
    simulation = get_object_or_404(Simulation, id=simulation_id)
    metadata = simulation.formatted_patient_history
    logger.debug(f"[Sim#{simulation.pk}] refreshed patient metadata: {metadata}")
    return render(
        request,
        "chatlab/partials/_metadata_patient_inner.html",
        context={"patient_metadata": metadata}
    )

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
