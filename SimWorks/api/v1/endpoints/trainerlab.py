"""TrainerLab API endpoints (iPadOS-first, JWT-only)."""

from collections.abc import Callable
from datetime import UTC
import json
import time
import uuid

from django.core.exceptions import ValidationError
from django.http import HttpRequest, StreamingHttpResponse
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import JWTAuth
from api.v1.schemas.common import PaginatedResponse
from api.v1.schemas.events import EventEnvelope
from api.v1.schemas.trainerlab import (
    IllnessCreateIn,
    InjuryCreateIn,
    InterventionCreateIn,
    LabAccessOut,
    RunSummaryOut,
    SteerPromptIn,
    TrainerCommandAck,
    TrainerSessionCreateIn,
    TrainerSessionOut,
    VitalCreateIn,
    trainer_session_to_out,
)
from apps.common.models import OutboxEvent
from apps.common.ratelimit import api_rate_limit
from apps.trainerlab.access import require_instructor_membership
from apps.trainerlab.models import (
    ETCO2,
    SPO2,
    ABCEvent,
    BloodGlucoseLevel,
    BloodPressure,
    EventSource,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    TrainerCommand,
    TrainerSession,
)
from apps.trainerlab.services import (
    create_session,
    emit_runtime_event,
    get_or_create_command,
    pause_session,
    resume_session,
    start_session,
    stop_session,
)

router = Router(tags=["trainerlab"], auth=JWTAuth())


def _get_idempotency_key(request: HttpRequest) -> str:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HttpError(400, "Idempotency-Key header is required")
    return key


def _get_session_for_user(session_id: int, user) -> TrainerSession:
    session = (
        TrainerSession.objects.select_related("simulation")
        .filter(pk=session_id, simulation__user=user)
        .first()
    )
    if session is None:
        raise HttpError(404, "Trainer session not found")
    return session


def _get_correlation_id(request: HttpRequest) -> str | None:
    return getattr(request, "correlation_id", None)


def _accepted(command: TrainerCommand) -> TrainerCommandAck:
    return TrainerCommandAck(command_id=str(command.id), status="accepted")


def _ensure_command_compatible(
    command: TrainerCommand,
    *,
    session: TrainerSession,
    command_type: str,
) -> None:
    if command.session_id != session.id or command.command_type != command_type:
        raise HttpError(409, "Idempotency-Key already used for a different command")

    if command.status == TrainerCommand.CommandStatus.FAILED:
        raise HttpError(409, command.error or "Command previously failed")


@router.get(
    "/access/me/",
    response=LabAccessOut,
    summary="Get TrainerLab access for current user",
)
@api_rate_limit
def trainerlab_access_me(request: HttpRequest) -> LabAccessOut:
    user = request.auth
    membership = require_instructor_membership(user)
    return LabAccessOut(lab_slug="trainerlab", access_level=membership.access_level)


@router.post(
    "/sessions/",
    response={201: TrainerSessionOut, 200: TrainerSessionOut},
    summary="Create TrainerLab session",
)
@api_rate_limit
def create_trainer_session(request: HttpRequest, body: TrainerSessionCreateIn) -> tuple[int, TrainerSessionOut]:
    user = request.auth
    require_instructor_membership(user)

    idempotency_key = _get_idempotency_key(request)
    existing = (
        TrainerCommand.objects.select_related("session__simulation")
        .filter(idempotency_key=idempotency_key)
        .first()
    )
    if existing:
        if existing.command_type != TrainerCommand.CommandType.CREATE_SESSION:
            raise HttpError(409, "Idempotency-Key already used for a different command")
        if existing.payload_json.get("action") != "create_session" or not existing.session_id:
            raise HttpError(409, "Idempotency-Key already used for a different command")
        if existing.session.simulation.user_id != user.id:
            raise HttpError(409, "Idempotency-Key already used")
        return 200, trainer_session_to_out(existing.session)

    session = create_session(
        user=user,
        scenario_spec=body.scenario_spec,
        directives=body.directives,
        modifiers=body.modifiers,
    )

    TrainerCommand.objects.create(
        session=session,
        command_type=TrainerCommand.CommandType.CREATE_SESSION,
        payload_json={"action": "create_session"},
        status=TrainerCommand.CommandStatus.PROCESSED,
        idempotency_key=idempotency_key,
        issued_by=user,
        processed_at=session.created_at,
    )

    return 201, trainer_session_to_out(session)


@router.get(
    "/sessions/",
    response=PaginatedResponse[TrainerSessionOut],
    summary="List TrainerLab sessions for user",
)
@api_rate_limit
def list_trainer_sessions(
    request: HttpRequest,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[TrainerSessionOut]:
    user = request.auth
    require_instructor_membership(user)

    queryset = TrainerSession.objects.select_related("simulation").filter(simulation__user=user).order_by("-id")

    if status:
        queryset = queryset.filter(status=status)

    if cursor:
        try:
            cursor_id = int(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None
        queryset = queryset.filter(pk__lt=cursor_id)

    rows = list(queryset[: limit + 1])
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor = str(rows[-1].id) if has_more and rows else None

    return PaginatedResponse(
        items=[trainer_session_to_out(row) for row in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/sessions/{session_id}/",
    response=TrainerSessionOut,
    summary="Get TrainerLab session",
)
@api_rate_limit
def get_trainer_session(request: HttpRequest, session_id: int) -> TrainerSessionOut:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_user(session_id, user)
    return trainer_session_to_out(session)


def _mark_command_failed(command: TrainerCommand, error: str) -> None:
    command.status = TrainerCommand.CommandStatus.FAILED
    command.error = error
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "error", "processed_at"])


def _process_run_command(request: HttpRequest, session_id: int, command_type: str) -> TrainerSessionOut:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    session = _get_session_for_user(session_id, user)

    command, created = get_or_create_command(
        session=session,
        command_type=command_type,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json={},
    )

    if not created:
        _ensure_command_compatible(command, session=session, command_type=command_type)
        if command.status == TrainerCommand.CommandStatus.PROCESSED:
            return trainer_session_to_out(session)

    try:
        if command_type == TrainerCommand.CommandType.START:
            session = start_session(session=session, user=user, correlation_id=correlation_id)
        elif command_type == TrainerCommand.CommandType.PAUSE:
            session = pause_session(session=session, user=user, correlation_id=correlation_id)
        elif command_type == TrainerCommand.CommandType.RESUME:
            session = resume_session(session=session, user=user, correlation_id=correlation_id)
        elif command_type == TrainerCommand.CommandType.STOP:
            session = stop_session(session=session, user=user, correlation_id=correlation_id)
        else:
            raise HttpError(400, "Unsupported command")
    except ValidationError as exc:
        _mark_command_failed(command, str(exc))
        raise HttpError(409, str(exc)) from None

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])

    return trainer_session_to_out(session)


@router.post("/sessions/{session_id}/run/start/", response=TrainerSessionOut, summary="Start TrainerLab run")
@api_rate_limit
def start_trainer_run(request: HttpRequest, session_id: int) -> TrainerSessionOut:
    return _process_run_command(request, session_id, TrainerCommand.CommandType.START)


@router.post("/sessions/{session_id}/run/pause/", response=TrainerSessionOut, summary="Pause TrainerLab run")
@api_rate_limit
def pause_trainer_run(request: HttpRequest, session_id: int) -> TrainerSessionOut:
    return _process_run_command(request, session_id, TrainerCommand.CommandType.PAUSE)


@router.post("/sessions/{session_id}/run/resume/", response=TrainerSessionOut, summary="Resume TrainerLab run")
@api_rate_limit
def resume_trainer_run(request: HttpRequest, session_id: int) -> TrainerSessionOut:
    return _process_run_command(request, session_id, TrainerCommand.CommandType.RESUME)


@router.post("/sessions/{session_id}/run/stop/", response=TrainerSessionOut, summary="Stop TrainerLab run")
@api_rate_limit
def stop_trainer_run(request: HttpRequest, session_id: int) -> TrainerSessionOut:
    return _process_run_command(request, session_id, TrainerCommand.CommandType.STOP)


@router.post(
    "/sessions/{session_id}/steer/prompt/",
    response=TrainerCommandAck,
    summary="Apply instructor steering prompt",
)
@api_rate_limit
def steer_prompt(request: HttpRequest, session_id: int, body: SteerPromptIn) -> TrainerCommandAck:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    session = _get_session_for_user(session_id, user)

    command, created = get_or_create_command(
        session=session,
        command_type=TrainerCommand.CommandType.STEER_PROMPT,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json={"prompt": body.prompt},
    )
    if not created:
        _ensure_command_compatible(
            command,
            session=session,
            command_type=TrainerCommand.CommandType.STEER_PROMPT,
        )
        if command.status == TrainerCommand.CommandStatus.PROCESSED:
            return _accepted(command)

    state = dict(session.runtime_state_json or {})
    prompts = list(state.get("steering_prompts", []))
    prompts.append(body.prompt)
    state["steering_prompts"] = prompts
    state["last_instruction"] = body.prompt
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.command.accepted",
        payload={
            "command": "steer_prompt",
            "prompt": body.prompt,
        },
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.command.accepted:{command.id}",
    )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])
    return _accepted(command)


def _resolve_superseded_domain_event(
    *,
    simulation_id: int,
    supersedes_event_id: int | None,
) -> ABCEvent | None:
    if not supersedes_event_id:
        return None
    return ABCEvent.objects.filter(pk=supersedes_event_id, simulation_id=simulation_id).first()


def _deactivate_superseded(event: ABCEvent | None) -> None:
    if event is None:
        return
    if event.is_active:
        event.is_active = False
        event.save(update_fields=["is_active"])


def _create_injury(session: TrainerSession, body: InjuryCreateIn) -> Injury:
    supersedes = _resolve_superseded_domain_event(
        simulation_id=session.simulation_id,
        supersedes_event_id=body.supersedes_event_id,
    )
    _deactivate_superseded(supersedes)

    parent_injury = None
    if body.parent_injury_id:
        parent_injury = Injury.objects.filter(
            pk=body.parent_injury_id,
            simulation_id=session.simulation_id,
        ).first()

    return Injury.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes_event=supersedes,
        injury_category=body.injury_category,
        injury_location=body.injury_location,
        injury_kind=body.injury_kind,
        injury_description=body.injury_description,
        parent_injury=parent_injury,
    )


def _create_illness(session: TrainerSession, body: IllnessCreateIn) -> Illness:
    supersedes = _resolve_superseded_domain_event(
        simulation_id=session.simulation_id,
        supersedes_event_id=body.supersedes_event_id,
    )
    _deactivate_superseded(supersedes)

    return Illness.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes_event=supersedes,
        name=body.name,
        description=body.description,
        severity=body.severity,
        is_resolved=body.is_resolved,
    )


def _create_intervention(session: TrainerSession, body: InterventionCreateIn) -> Intervention:
    supersedes = _resolve_superseded_domain_event(
        simulation_id=session.simulation_id,
        supersedes_event_id=body.supersedes_event_id,
    )
    _deactivate_superseded(supersedes)

    return Intervention.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes_event=supersedes,
        code=body.code,
        description=body.description,
        target=body.target,
    )


def _create_vital(session: TrainerSession, body: VitalCreateIn) -> ABCEvent:
    supersedes = _resolve_superseded_domain_event(
        simulation_id=session.simulation_id,
        supersedes_event_id=body.supersedes_event_id,
    )
    _deactivate_superseded(supersedes)

    common = {
        "simulation": session.simulation,
        "source": EventSource.INSTRUCTOR,
        "supersedes_event": supersedes,
        "min_value": body.min_value,
        "max_value": body.max_value,
        "lock_value": body.lock_value,
    }

    if body.vital_type == "heart_rate":
        return HeartRate.objects.create(**common)
    if body.vital_type == "spo2":
        return SPO2.objects.create(**common)
    if body.vital_type == "etco2":
        return ETCO2.objects.create(**common)
    if body.vital_type == "blood_glucose":
        return BloodGlucoseLevel.objects.create(**common)

    if body.min_value_diastolic is None or body.max_value_diastolic is None:
        raise HttpError(400, "Blood pressure requires min_value_diastolic and max_value_diastolic")

    return BloodPressure.objects.create(
        **common,
        min_value_diastolic=body.min_value_diastolic,
        max_value_diastolic=body.max_value_diastolic,
    )


def _inject_event_core(
    *,
    request: HttpRequest,
    session_id: int,
    command_type: str,
    payload_json: dict,
    create_fn: Callable[[TrainerSession], ABCEvent],
) -> TrainerCommandAck:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    session = _get_session_for_user(session_id, user)

    command, created = get_or_create_command(
        session=session,
        command_type=command_type,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json=payload_json,
    )
    if not created:
        _ensure_command_compatible(command, session=session, command_type=command_type)
        if command.status == TrainerCommand.CommandStatus.PROCESSED:
            return _accepted(command)

    try:
        domain_event = create_fn(session)
    except ValidationError as exc:
        _mark_command_failed(command, str(exc))
        raise HttpError(409, str(exc)) from None

    emit_runtime_event(
        session=session,
        event_type="trainerlab.event.created",
        payload={
            "domain_event_id": domain_event.id,
            "domain_event_type": domain_event.__class__.__name__,
            "source": domain_event.source,
            "supersedes_event_id": domain_event.supersedes_event_id,
        },
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.event.created:{domain_event.id}",
    )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])
    return _accepted(command)


@router.post(
    "/sessions/{session_id}/events/injuries/",
    response=TrainerCommandAck,
    summary="Inject injury event",
)
@api_rate_limit
def create_injury_event(
    request: HttpRequest,
    session_id: int,
    body: InjuryCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        session_id=session_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "injury", **body.model_dump()},
        create_fn=lambda session: _create_injury(session, body),
    )


@router.post(
    "/sessions/{session_id}/events/illnesses/",
    response=TrainerCommandAck,
    summary="Inject illness event",
)
@api_rate_limit
def create_illness_event(
    request: HttpRequest,
    session_id: int,
    body: IllnessCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        session_id=session_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "illness", **body.model_dump()},
        create_fn=lambda session: _create_illness(session, body),
    )


@router.post(
    "/sessions/{session_id}/events/interventions/",
    response=TrainerCommandAck,
    summary="Inject intervention event",
)
@api_rate_limit
def create_intervention_event(
    request: HttpRequest,
    session_id: int,
    body: InterventionCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        session_id=session_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "intervention", **body.model_dump()},
        create_fn=lambda session: _create_intervention(session, body),
    )


@router.post(
    "/sessions/{session_id}/events/vitals/",
    response=TrainerCommandAck,
    summary="Inject vital event",
)
@api_rate_limit
def create_vital_event(
    request: HttpRequest,
    session_id: int,
    body: VitalCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        session_id=session_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "vital", **body.model_dump()},
        create_fn=lambda session: _create_vital(session, body),
    )


@router.get(
    "/sessions/{session_id}/events/",
    response=PaginatedResponse[EventEnvelope],
    summary="List TrainerLab runtime events",
)
@api_rate_limit
def list_trainer_events(
    request: HttpRequest,
    session_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[EventEnvelope]:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_user(session_id, user)

    queryset = OutboxEvent.objects.filter(
        simulation_id=session.simulation_id,
        event_type__startswith="trainerlab.",
    ).order_by("created_at")

    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None

        cursor_event = OutboxEvent.objects.filter(
            id=cursor_uuid,
            simulation_id=session.simulation_id,
            event_type__startswith="trainerlab.",
        ).first()
        if cursor_event is None:
            raise HttpError(400, "Invalid cursor")

        queryset = queryset.filter(created_at__gt=cursor_event.created_at)

    events = list(queryset[: limit + 1])
    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    next_cursor = str(events[-1].id) if has_more and events else None

    items = [
        EventEnvelope(
            event_id=str(event.id),
            event_type=event.event_type,
            created_at=event.created_at,
            correlation_id=event.correlation_id,
            payload=event.payload,
        )
        for event in events
    ]

    return PaginatedResponse(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/sessions/{session_id}/summary/",
    response=RunSummaryOut,
    summary="Get run summary",
)
@api_rate_limit
def get_run_summary(request: HttpRequest, session_id: int) -> RunSummaryOut:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_user(session_id, user)

    summary = getattr(session, "summary", None)
    if summary is None:
        raise HttpError(404, "Summary not generated")

    return RunSummaryOut(**summary.summary_json)


@router.get(
    "/sessions/{session_id}/events/stream/",
    summary="SSE stream for TrainerLab events",
)
def stream_trainer_events(
    request: HttpRequest,
    session_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
) -> StreamingHttpResponse:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_user(session_id, user)

    initial_created_at = None
    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None

        cursor_event = OutboxEvent.objects.filter(
            id=cursor_uuid,
            simulation_id=session.simulation_id,
            event_type__startswith="trainerlab.",
        ).first()
        if cursor_event is None:
            raise HttpError(400, "Invalid cursor")
        initial_created_at = cursor_event.created_at

    def event_stream():
        last_created_at = initial_created_at

        while True:
            queryset = OutboxEvent.objects.filter(
                simulation_id=session.simulation_id,
                event_type__startswith="trainerlab.",
            ).order_by("created_at")

            if last_created_at is not None:
                queryset = queryset.filter(created_at__gt=last_created_at)

            events = list(queryset[:100])
            for event in events:
                data = {
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "created_at": event.created_at.astimezone(UTC).isoformat(),
                    "correlation_id": event.correlation_id,
                    "payload": event.payload,
                }
                yield f"id: {event.id}\n"
                yield "event: trainerlab\n"
                yield f"data: {json.dumps(data)}\n\n"
                last_created_at = event.created_at

            yield ": keepalive\n\n"
            time.sleep(1)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
