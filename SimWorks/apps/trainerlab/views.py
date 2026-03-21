import logging

from asgiref.sync import sync_to_async
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from api.v1.sse import stream_outbox_events
from apps.common.decorators import resolve_user
from apps.common.models import OutboxEvent
from apps.common.outbox.outbox import order_outbox_queryset
from apps.common.watch import build_watch_page_context, build_watch_service_calls_context
from apps.simcore.models import Simulation
from apps.trainerlab.access import has_instructor_access
from apps.trainerlab.utils import create_new_simulation
from orchestrai_django.models import ServiceCall

logger = logging.getLogger(__name__)


@login_required
def index(request):
    """TrainerLab home page."""
    return render(request, "trainerlab/index.html", {})


@login_required
@resolve_user
async def run_simulation(request, simulation_id):
    """TrainerLab simulation runner — stub until fully implemented."""
    try:
        await Simulation.objects.aget(id=simulation_id)
    except Simulation.DoesNotExist as err:
        raise Http404("Simulation not found.") from err

    if not await sync_to_async(has_instructor_access)(request.user):
        return HttpResponseForbidden("Instructor access required.")

    logger.debug("run_simulation: user=%s sim=%s", request.user.pk, simulation_id)
    return HttpResponse("TrainerLab simulation runner — coming soon.", content_type="text/plain")


@login_required
@resolve_user
@require_http_methods(["GET", "POST"])
async def create_simulation(request):
    if request.method == "GET":
        return redirect("trainerlab:create_session", simulation_id=None)

    # Otherwise, request must be POST
    modifiers = request.POST.getlist("modifier")
    simulation = await create_new_simulation(user=request.user, modifiers=modifiers)
    return redirect("trainerlab:run_simulation", simulation_id=simulation.id)


# ---------------------------------------------------------------------------
# Admin watch views
# ---------------------------------------------------------------------------


@staff_member_required
def watch_simulation(request, simulation_id):
    """Admin-only live event watch view for a TrainerLab simulation."""
    logger.info(
        "watch_simulation: admin=%s viewing sim=%s (trainerlab)",
        request.user.pk,
        simulation_id,
    )
    simulation = get_object_or_404(Simulation, id=simulation_id)
    outbox_qs = order_outbox_queryset(OutboxEvent.objects.filter(simulation_id=simulation_id))
    service_calls_qs = ServiceCall.objects.for_simulation(simulation_id).order_by("created_at")
    run_url = reverse("trainerlab:run_simulation", args=[simulation_id])

    context = build_watch_page_context(
        request=request,
        simulation=simulation,
        outbox_events=outbox_qs,
        service_calls_qs=service_calls_qs,
        stream_url=reverse("trainerlab:watch_stream", args=[simulation_id]),
        service_calls_url=reverse("trainerlab:watch_service_calls", args=[simulation_id]),
        watch_url=reverse("trainerlab:watch_simulation", args=[simulation_id]),
        back_url=run_url,
        lab_name="TrainerLab",
        can_go_to_simulation=has_instructor_access(request.user),
        go_to_simulation_url=run_url,
    )
    return render(
        request,
        "simulation_watch.html",
        context,
    )


@staff_member_required
def watch_stream(request, simulation_id):
    """SSE stream for the admin watch view (session-cookie auth)."""
    logger.debug(
        "watch_stream: SSE opened admin=%s sim=%s cursor=%s (trainerlab)",
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
        "watch_service_calls: admin=%s sim=%s (trainerlab)",
        request.user.pk,
        simulation_id,
    )
    get_object_or_404(Simulation, id=simulation_id)
    service_calls_qs = ServiceCall.objects.for_simulation(simulation_id).order_by("created_at")
    return render(
        request,
        "partials/watch_service_calls.html",
        build_watch_service_calls_context(
            request=request,
            service_calls_qs=service_calls_qs,
            service_calls_url=reverse("trainerlab:watch_service_calls", args=[simulation_id]),
            watch_url=reverse("trainerlab:watch_simulation", args=[simulation_id]),
        ),
    )
