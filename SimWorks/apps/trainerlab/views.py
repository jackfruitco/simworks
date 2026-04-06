import json
import logging

from asgiref.sync import sync_to_async
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.serializers.json import DjangoJSONEncoder
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from api.v1.sse import build_outbox_events_stream_response, resolve_outbox_stream_anchor
from apps.accounts.context import resolve_request_account
from apps.common.decorators import resolve_user
from apps.common.models import OutboxEvent
from apps.common.outbox.outbox import order_outbox_queryset
from apps.common.watch import build_watch_page_context, build_watch_service_calls_context
from apps.simcore.access import can_access_simulation_in_request
from apps.simcore.models import Simulation
from apps.trainerlab.access import has_lab_access_for_request
from apps.trainerlab.models import TrainerSession
from apps.trainerlab.utils import create_new_simulation
from apps.trainerlab.viewmodels import build_trainer_watch_view_model, load_trainer_engine_aggregate
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
        simulation = await Simulation.objects.select_related("user", "account").aget(
            id=simulation_id
        )
    except Simulation.DoesNotExist as err:
        raise Http404("Simulation not found.") from err

    if not await sync_to_async(can_access_simulation_in_request)(request.user, simulation, request):
        return HttpResponseForbidden("This isn't your simulation.")

    if not await sync_to_async(has_lab_access_for_request)(request.user, request=request):
        return HttpResponseForbidden("TrainerLab access required.")

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
    account = await sync_to_async(resolve_request_account)(request, user=request.user)
    if account is None:
        return HttpResponseForbidden("Account access required.")
    simulation = await create_new_simulation(
        user=request.user,
        modifiers=modifiers,
        account=account,
    )
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
        realtime_transport="sse",
        service_calls_url=reverse("trainerlab:watch_service_calls", args=[simulation_id]),
        watch_url=reverse("trainerlab:watch_simulation", args=[simulation_id]),
        back_url=run_url,
        lab_name="TrainerLab",
        can_go_to_simulation=has_lab_access_for_request(request.user, request=request),
        go_to_simulation_url=run_url,
    )
    try:
        trainer_watch_view_model = build_trainer_watch_view_model(
            load_trainer_engine_aggregate(simulation_id=simulation_id)
        )
    except TrainerSession.DoesNotExist:
        logger.info(
            "trainerlab.watch.aggregate_missing",
            extra={"simulation_id": simulation_id},
        )
    else:
        context.update(
            {
                "watch_detail_partial": "trainerlab/partials/watch_details.html",
                "trainer_watch_scenario_state_json": json.dumps(
                    trainer_watch_view_model.watch_snapshot.scenario_state_summary.model_dump(
                        mode="json"
                    ),
                    cls=DjangoJSONEncoder,
                    indent=2,
                ),
                "trainer_watch_runtime_state_json": json.dumps(
                    trainer_watch_view_model.watch_snapshot.runtime_state_summary.model_dump(
                        mode="json"
                    ),
                    cls=DjangoJSONEncoder,
                    indent=2,
                ),
                "trainer_watch_scenario_snapshot_json": json.dumps(
                    trainer_watch_view_model.scenario_snapshot.model_dump(mode="json"),
                    cls=DjangoJSONEncoder,
                    indent=2,
                ),
                "trainer_watch_runtime_snapshot_json": json.dumps(
                    trainer_watch_view_model.runtime_snapshot.model_dump(mode="json"),
                    cls=DjangoJSONEncoder,
                    indent=2,
                ),
                "trainer_watch_event_timeline_json": json.dumps(
                    trainer_watch_view_model.event_timeline.model_dump(mode="json"),
                    cls=DjangoJSONEncoder,
                    indent=2,
                ),
                "trainer_watch_snapshot_cache_json": json.dumps(
                    trainer_watch_view_model.watch_snapshot.snapshot_cache.model_dump(mode="json"),
                    cls=DjangoJSONEncoder,
                    indent=2,
                ),
            }
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
    last_event = resolve_outbox_stream_anchor(
        simulation_id=simulation_id,
        cursor=cursor,
        event_type_prefix=event_type_prefix,
    )
    return build_outbox_events_stream_response(
        simulation_id=simulation_id,
        last_event=last_event,
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
