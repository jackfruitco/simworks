"""TrainerLab API endpoints (iPadOS-first, JWT-only)."""

from collections.abc import Callable
from datetime import UTC
from typing import Any
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, StreamingHttpResponse
from django.utils import timezone
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import JWTAuth
from api.v1.schemas.common import PaginatedResponse
from api.v1.schemas.events import EventEnvelope
from api.v1.schemas.trainerlab import (
    DictionaryItemOut,
    IllnessCreateIn,
    InjuryCreateIn,
    InterventionCreateIn,
    InterventionGroupOut,
    LabAccessOut,
    RunSummaryOut,
    ScenarioInstructionApplyIn,
    ScenarioInstructionCreateIn,
    ScenarioInstructionOut,
    ScenarioInstructionPermissionIn,
    ScenarioInstructionPermissionOut,
    ScenarioInstructionUnshareIn,
    ScenarioInstructionUpdateIn,
    SimulationAdjustAck,
    SimulationAdjustIn,
    SteerPromptIn,
    TrainerCommandAck,
    TrainerRunOut,
    TrainerSessionCreateIn,
    VitalCreateIn,
    scenario_instruction_to_out,
    scenario_permission_to_out,
    trainer_run_to_out,
)
from api.v1.sse import stream_outbox_events
from apps.common.models import OutboxEvent
from apps.common.outbox.outbox import apply_outbox_cursor, order_outbox_queryset
from apps.common.ratelimit import api_rate_limit
from apps.simcore.models import Simulation
from apps.trainerlab.access import require_instructor_membership
from apps.trainerlab.injury_dictionary import get_injury_dictionary_choices
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
    ScenarioInstruction,
    ScenarioInstructionPermission,
    TrainerCommand,
    TrainerSession,
)
from apps.trainerlab.services import (
    create_session_with_initial_generation,
    emit_runtime_event,
    get_or_create_command,
    pause_session,
    resume_session,
    start_session,
    stop_session,
)

router = Router(tags=["trainerlab"], auth=JWTAuth())
UserModel = get_user_model()

INTERVENTION_DICTIONARY: list[InterventionGroupOut] = [
    InterventionGroupOut(
        group="Tourniquet",
        items=[
            DictionaryItemOut(code="M-TQ-H", label="Hasty Tourniquet"),
            DictionaryItemOut(code="M-TQ-D", label="Deliberate Tourniquet"),
        ],
    ),
    InterventionGroupOut(
        group="Gauze",
        items=[
            DictionaryItemOut(code="M-GZ-PK", label="Non-Hemostatic Gauze Packed"),
            DictionaryItemOut(code="M-GZ-PK-H", label="Hemostatic Gauze Packed"),
            DictionaryItemOut(code="M-GZ-WP", label="Non-Hemostatic Gauze Wrapped"),
            DictionaryItemOut(code="M-GZ-WP-H", label="Hemostatic Gauze Wrapped"),
            DictionaryItemOut(code="M-GZ-ZF", label="Z-Folded Gauze"),
            DictionaryItemOut(code="M-GZ-ZF-H", label="Hemostatic Z-Folded Gauze"),
        ],
    ),
    InterventionGroupOut(
        group="Airway",
        items=[
            DictionaryItemOut(code="A-P-R", label="Recovery Position"),
            DictionaryItemOut(code="A-P-C", label="Position of Comfort"),
            DictionaryItemOut(code="A-P-O", label="Other Position"),
            DictionaryItemOut(code="A-HTCL", label="Head-Tilt-Chin-Lift"),
            DictionaryItemOut(code="A-JT", label="Jaw-Thrust"),
            DictionaryItemOut(code="A-NPA", label="NPA"),
            DictionaryItemOut(code="A-OPA", label="OPA"),
            DictionaryItemOut(code="A-SGA", label="SGA"),
            DictionaryItemOut(code="A-INT", label="Intubation"),
            DictionaryItemOut(code="A-SURG-O", label="Surgical Airway (Open Technique)"),
            DictionaryItemOut(code="A-SURG-B", label="Surgical Airway (Bougie-aided)"),
        ],
    ),
]


def _get_idempotency_key(request: HttpRequest) -> str:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HttpError(400, "Idempotency-Key header is required")
    return key


def _get_session_for_simulation(simulation_id: int, user) -> TrainerSession:
    session = (
        TrainerSession.objects.select_related("simulation")
        .filter(simulation_id=simulation_id, simulation__user=user)
        .first()
    )
    if session is None:
        raise HttpError(404, "Trainer session not found")
    return session


def _get_correlation_id(request: HttpRequest) -> str | None:
    return getattr(request, "correlation_id", None)


def _accepted(command: TrainerCommand) -> TrainerCommandAck:
    return TrainerCommandAck(command_id=str(command.id), status="accepted")


def _normalize_command_payload(payload_json: dict[str, Any] | None) -> dict[str, Any]:
    return payload_json or {}


def _build_dict_items(choices) -> list[DictionaryItemOut]:
    return [DictionaryItemOut(code=code, label=str(label)) for code, label in choices]


def _claim_command(
    *,
    session: TrainerSession,
    command_type: str,
    idempotency_key: str,
    issued_by,
    payload_json: dict[str, Any] | None = None,
) -> tuple[TrainerCommand, bool]:
    normalized_payload = _normalize_command_payload(payload_json)
    command, created = get_or_create_command(
        session=session,
        command_type=command_type,
        idempotency_key=idempotency_key,
        issued_by=issued_by,
        payload_json=normalized_payload,
    )
    if created:
        return command, True

    _ensure_command_compatible(
        command,
        session=session,
        command_type=command_type,
        payload_json=normalized_payload,
    )
    return command, False


def _ensure_command_compatible(
    command: TrainerCommand,
    *,
    session: TrainerSession,
    command_type: str,
    payload_json: dict[str, Any] | None = None,
) -> None:
    if command.session_id != session.id or command.command_type != command_type:
        raise HttpError(409, "Idempotency-Key already used for a different command")
    if (command.payload_json or {}) != _normalize_command_payload(payload_json):
        raise HttpError(409, "Idempotency-Key already used for a different request payload")

    if command.status == TrainerCommand.CommandStatus.FAILED:
        raise HttpError(409, command.error or "Command previously failed")


def _replay_create_session(
    *,
    user,
    idempotency_key: str,
    payload_json: dict[str, Any],
) -> TrainerSession | None:
    existing = (
        TrainerCommand.objects.select_related("session__simulation")
        .filter(idempotency_key=idempotency_key)
        .first()
    )
    if existing is None:
        return None

    if existing.command_type != TrainerCommand.CommandType.CREATE_SESSION:
        raise HttpError(409, "Idempotency-Key already used for a different command")
    if not existing.session_id or existing.session is None:
        raise HttpError(409, "Idempotency-Key already used for a different command")
    if existing.session.simulation.user_id != user.id:
        raise HttpError(409, "Idempotency-Key already used")
    if (existing.payload_json or {}) != payload_json:
        raise HttpError(409, "Idempotency-Key already used for a different request payload")
    return existing.session


def _instruction_queryset_for_user(user):
    return (
        ScenarioInstruction.objects.filter(
            Q(owner=user) | Q(permissions__user=user, permissions__can_read=True)
        )
        .prefetch_related("permissions")
        .distinct()
        .order_by("-id")
    )


def _get_instruction_for_user(
    preset_id: int,
    user,
    *,
    require_edit: bool = False,
    require_delete: bool = False,
    require_share: bool = False,
    require_duplicate: bool = False,
) -> ScenarioInstruction:
    instruction = (
        ScenarioInstruction.objects.filter(pk=preset_id).prefetch_related("permissions").first()
    )
    if instruction is None:
        raise HttpError(404, "Scenario preset not found")

    if instruction.owner_id == user.id:
        return instruction

    permission = ScenarioInstructionPermission.objects.filter(
        scenario_instruction=instruction,
        user=user,
    ).first()
    if permission is None or not permission.can_read:
        raise HttpError(404, "Scenario preset not found")

    if require_edit and not permission.can_edit:
        raise HttpError(403, "Edit access required")
    if require_delete and not permission.can_delete:
        raise HttpError(403, "Delete access required")
    if require_share and not permission.can_share:
        raise HttpError(403, "Share access required")
    if require_duplicate and not permission.can_duplicate:
        raise HttpError(403, "Duplicate access required")

    return instruction


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


@router.get(
    "/dictionaries/injuries/",
    response=dict[str, list[DictionaryItemOut]],
    summary="List injury dictionary mappings",
)
@api_rate_limit
def injury_dictionary(request: HttpRequest) -> dict[str, list[DictionaryItemOut]]:
    user = request.auth
    require_instructor_membership(user)
    return {
        key: _build_dict_items(choices) for key, choices in get_injury_dictionary_choices().items()
    }


@router.get(
    "/dictionaries/interventions/",
    response=list[InterventionGroupOut],
    summary="List intervention dictionary mappings",
)
@api_rate_limit
def intervention_dictionary(request: HttpRequest) -> list[InterventionGroupOut]:
    user = request.auth
    require_instructor_membership(user)
    return INTERVENTION_DICTIONARY


@router.get(
    "/presets/",
    response=PaginatedResponse[ScenarioInstructionOut],
    summary="List accessible TrainerLab scenario presets",
)
@api_rate_limit
def list_presets(
    request: HttpRequest,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[ScenarioInstructionOut]:
    user = request.auth
    require_instructor_membership(user)
    queryset = _instruction_queryset_for_user(user)

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
        items=[scenario_instruction_to_out(item) for item in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/presets/",
    response={201: ScenarioInstructionOut},
    summary="Create TrainerLab scenario preset",
)
@api_rate_limit
def create_preset(
    request: HttpRequest, body: ScenarioInstructionCreateIn
) -> tuple[int, ScenarioInstructionOut]:
    user = request.auth
    require_instructor_membership(user)
    instruction = ScenarioInstruction.objects.create(
        owner=user,
        title=body.title,
        description=body.description,
        instruction_text=body.instruction_text,
        injuries_json=body.injuries,
        severity=body.severity,
        metadata_json=body.metadata,
    )
    return 201, scenario_instruction_to_out(instruction)


@router.get(
    "/presets/{preset_id}/",
    response=ScenarioInstructionOut,
    summary="Get TrainerLab scenario preset",
)
@api_rate_limit
def get_preset(request: HttpRequest, preset_id: int) -> ScenarioInstructionOut:
    user = request.auth
    require_instructor_membership(user)
    instruction = _get_instruction_for_user(preset_id, user)
    return scenario_instruction_to_out(instruction)


@router.patch(
    "/presets/{preset_id}/",
    response=ScenarioInstructionOut,
    summary="Update TrainerLab scenario preset",
)
@api_rate_limit
def update_preset(
    request: HttpRequest, preset_id: int, body: ScenarioInstructionUpdateIn
) -> ScenarioInstructionOut:
    user = request.auth
    require_instructor_membership(user)
    instruction = _get_instruction_for_user(preset_id, user, require_edit=True)
    updates = body.model_dump(exclude_none=True)
    if "injuries" in updates:
        updates["injuries_json"] = updates.pop("injuries")
    if "metadata" in updates:
        updates["metadata_json"] = updates.pop("metadata")
    for key, value in updates.items():
        setattr(instruction, key, value)
    if updates:
        instruction.save(update_fields=[*updates.keys(), "modified_at"])
    instruction.refresh_from_db()
    return scenario_instruction_to_out(instruction)


@router.delete(
    "/presets/{preset_id}/",
    response={204: None},
    summary="Delete TrainerLab scenario preset",
)
@api_rate_limit
def delete_preset(request: HttpRequest, preset_id: int) -> tuple[int, None]:
    user = request.auth
    require_instructor_membership(user)
    instruction = _get_instruction_for_user(preset_id, user, require_delete=True)
    instruction.delete()
    return 204, None


@router.post(
    "/presets/{preset_id}/duplicate/",
    response={201: ScenarioInstructionOut},
    summary="Duplicate TrainerLab scenario preset",
)
@api_rate_limit
def duplicate_preset(request: HttpRequest, preset_id: int) -> tuple[int, ScenarioInstructionOut]:
    user = request.auth
    require_instructor_membership(user)
    source = _get_instruction_for_user(preset_id, user, require_duplicate=True)
    metadata = dict(source.metadata_json or {})
    metadata["source_preset_id"] = source.id
    duplicate = ScenarioInstruction.objects.create(
        owner=user,
        title=f"{source.title} (Copy)",
        description=source.description,
        instruction_text=source.instruction_text,
        injuries_json=list(source.injuries_json or []),
        severity=source.severity,
        metadata_json=metadata,
    )
    return 201, scenario_instruction_to_out(duplicate)


@router.post(
    "/presets/{preset_id}/share/",
    response=ScenarioInstructionPermissionOut,
    summary="Share TrainerLab scenario preset with a user",
)
@api_rate_limit
def share_preset(
    request: HttpRequest, preset_id: int, body: ScenarioInstructionPermissionIn
) -> ScenarioInstructionPermissionOut:
    user = request.auth
    require_instructor_membership(user)
    instruction = _get_instruction_for_user(preset_id, user, require_share=True)
    target = UserModel.objects.filter(pk=body.user_id, is_active=True).first()
    if target is None:
        raise HttpError(404, "Target user not found")
    if target.id == instruction.owner_id:
        raise HttpError(400, "Owner already has full preset access")

    permission, _ = ScenarioInstructionPermission.objects.update_or_create(
        scenario_instruction=instruction,
        user=target,
        defaults={
            "can_read": body.can_read,
            "can_edit": body.can_edit,
            "can_delete": body.can_delete,
            "can_share": body.can_share,
            "can_duplicate": body.can_duplicate,
            "granted_by": user,
        },
    )
    return scenario_permission_to_out(permission)


@router.post(
    "/presets/{preset_id}/unshare/",
    response={204: None},
    summary="Remove shared access for a TrainerLab scenario preset",
)
@api_rate_limit
def unshare_preset(
    request: HttpRequest,
    preset_id: int,
    body: ScenarioInstructionUnshareIn,
) -> tuple[int, None]:
    user = request.auth
    require_instructor_membership(user)
    instruction = _get_instruction_for_user(preset_id, user, require_share=True)
    if body.user_id == instruction.owner_id:
        raise HttpError(400, "Owner permissions cannot be removed")
    ScenarioInstructionPermission.objects.filter(
        scenario_instruction=instruction,
        user_id=body.user_id,
    ).delete()
    return 204, None


@router.post(
    "/presets/{preset_id}/apply/",
    response=TrainerCommandAck,
    summary="Apply preset instructions to a TrainerLab simulation",
)
@api_rate_limit
def apply_preset(
    request: HttpRequest,
    preset_id: int,
    body: ScenarioInstructionApplyIn,
) -> TrainerCommandAck:
    user = request.auth
    require_instructor_membership(user)
    instruction = _get_instruction_for_user(preset_id, user)
    session = _get_session_for_simulation(body.simulation_id, user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    payload = {"preset_id": instruction.id, "simulation_id": session.simulation_id}
    command, created = _claim_command(
        session=session,
        command_type=TrainerCommand.CommandType.APPLY_PRESET,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json=payload,
    )
    if not created and command.status == TrainerCommand.CommandStatus.PROCESSED:
        return _accepted(command)

    state = dict(session.runtime_state_json or {})
    applied_presets = list(state.get("applied_presets", []))
    applied_presets.append(
        {
            "preset_id": instruction.id,
            "title": instruction.title,
            "applied_at": timezone.now().astimezone(UTC).isoformat(),
        }
    )
    state["applied_presets"] = applied_presets
    if instruction.instruction_text:
        state["last_instruction"] = instruction.instruction_text
        session.initial_directives = instruction.instruction_text
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "initial_directives", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.preset.applied",
        payload={
            "preset_id": instruction.id,
            "title": instruction.title,
        },
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.preset.applied:{session.id}:{instruction.id}",
    )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])
    return _accepted(command)


@router.post(
    "/simulations/",
    response={201: TrainerRunOut, 200: TrainerRunOut},
    summary="Create TrainerLab simulation",
)
@api_rate_limit
def create_trainer_session(
    request: HttpRequest, body: TrainerSessionCreateIn
) -> tuple[int, TrainerRunOut]:
    user = request.auth
    require_instructor_membership(user)

    idempotency_key = _get_idempotency_key(request)
    payload = {
        "action": "create_session",
        "scenario_spec": body.scenario_spec,
        "directives": body.directives,
        "modifiers": body.modifiers,
    }
    existing = _replay_create_session(
        user=user,
        idempotency_key=idempotency_key,
        payload_json=payload,
    )
    if existing is not None:
        return 200, trainer_run_to_out(existing)

    session, _call_id = create_session_with_initial_generation(
        user=user,
        scenario_spec=body.scenario_spec,
        directives=body.directives,
        modifiers=body.modifiers,
    )

    TrainerCommand.objects.create(
        session=session,
        command_type=TrainerCommand.CommandType.CREATE_SESSION,
        payload_json=payload,
        status=TrainerCommand.CommandStatus.PROCESSED,
        idempotency_key=idempotency_key,
        issued_by=user,
        processed_at=session.created_at,
    )

    return 201, trainer_run_to_out(session)


@router.get(
    "/simulations/",
    response=PaginatedResponse[TrainerRunOut],
    summary="List TrainerLab simulations for user",
)
@api_rate_limit
def list_trainer_sessions(
    request: HttpRequest,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> PaginatedResponse[TrainerRunOut]:
    user = request.auth
    require_instructor_membership(user)

    queryset = (
        TrainerSession.objects.select_related("simulation")
        .filter(simulation__user=user)
        .order_by("-id")
    )

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
        items=[trainer_run_to_out(row) for row in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/simulations/{simulation_id}/",
    response=TrainerRunOut,
    summary="Get TrainerLab simulation",
)
@api_rate_limit
def get_trainer_session(request: HttpRequest, simulation_id: int) -> TrainerRunOut:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    return trainer_run_to_out(session)


def _mark_command_failed(command: TrainerCommand, error: str) -> None:
    command.status = TrainerCommand.CommandStatus.FAILED
    command.error = error
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "error", "processed_at"])


def _process_run_command(
    request: HttpRequest, simulation_id: int, command_type: str
) -> TrainerRunOut:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    session = _get_session_for_simulation(simulation_id, user)

    command, created = _claim_command(
        session=session,
        command_type=command_type,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json={},
    )
    if not created and command.status == TrainerCommand.CommandStatus.PROCESSED:
        return trainer_run_to_out(session)

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

    return trainer_run_to_out(session)


@router.post(
    "/simulations/{simulation_id}/run/start/",
    response=TrainerRunOut,
    summary="Start TrainerLab run",
)
@api_rate_limit
def start_trainer_run(request: HttpRequest, simulation_id: int) -> TrainerRunOut:
    return _process_run_command(request, simulation_id, TrainerCommand.CommandType.START)


@router.post(
    "/simulations/{simulation_id}/run/pause/",
    response=TrainerRunOut,
    summary="Pause TrainerLab run",
)
@api_rate_limit
def pause_trainer_run(request: HttpRequest, simulation_id: int) -> TrainerRunOut:
    return _process_run_command(request, simulation_id, TrainerCommand.CommandType.PAUSE)


@router.post(
    "/simulations/{simulation_id}/run/resume/",
    response=TrainerRunOut,
    summary="Resume TrainerLab run",
)
@api_rate_limit
def resume_trainer_run(request: HttpRequest, simulation_id: int) -> TrainerRunOut:
    return _process_run_command(request, simulation_id, TrainerCommand.CommandType.RESUME)


@router.post(
    "/simulations/{simulation_id}/run/stop/",
    response=TrainerRunOut,
    summary="Stop TrainerLab run",
)
@api_rate_limit
def stop_trainer_run(request: HttpRequest, simulation_id: int) -> TrainerRunOut:
    return _process_run_command(request, simulation_id, TrainerCommand.CommandType.STOP)


@router.post(
    "/simulations/{simulation_id}/steer/prompt/",
    response=TrainerCommandAck,
    summary="Apply instructor steering prompt",
)
@api_rate_limit
def steer_prompt(
    request: HttpRequest, simulation_id: int, body: SteerPromptIn
) -> TrainerCommandAck:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    session = _get_session_for_simulation(simulation_id, user)

    command, created = _claim_command(
        session=session,
        command_type=TrainerCommand.CommandType.STEER_PROMPT,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json={"prompt": body.prompt},
    )
    if not created and command.status == TrainerCommand.CommandStatus.PROCESSED:
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


@router.post(
    "/simulations/{simulation_id}/adjust/",
    response=SimulationAdjustAck,
    summary="Adjust a TrainerLab simulation scenario",
)
@api_rate_limit
def adjust_simulation(
    request: HttpRequest,
    simulation_id: int,
    body: SimulationAdjustIn,
) -> SimulationAdjustAck:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    simulation = Simulation.objects.filter(pk=simulation_id, user=user).first()
    if simulation is None:
        raise HttpError(404, "Simulation not found")

    session = _get_session_for_simulation(simulation_id, user)

    payload = body.model_dump()
    command, created = _claim_command(
        session=session,
        command_type=TrainerCommand.CommandType.ADJUST_SCENARIO,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json=payload,
    )
    if not created and command.status == TrainerCommand.CommandStatus.PROCESSED:
        return SimulationAdjustAck(
            command_id=str(command.id),
            status="accepted",
            simulation_id=simulation.id,
        )

    adjustment_entry = {
        "command_id": str(command.id),
        "target": body.target,
        "direction": body.direction,
        "magnitude": body.magnitude,
        "injury_event_id": body.injury_event_id,
        "injury_region": body.injury_region,
        "avpu_state": body.avpu_state,
        "intervention_code": body.intervention_code,
        "note": body.note,
        "metadata": body.metadata,
        "issued_at": timezone.now().isoformat(),
    }
    state = dict(session.runtime_state_json or {})
    adjustments = list(state.get("adjustments", []))
    adjustments.append(adjustment_entry)
    state["adjustments"] = adjustments
    if body.note:
        state["last_instruction"] = body.note
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="trainerlab.adjustment.accepted",
        payload=adjustment_entry,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.adjustment.accepted:{command.id}",
    )
    emit_runtime_event(
        session=session,
        event_type="trainerlab.adjustment.applied",
        payload=adjustment_entry,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"trainerlab.adjustment.applied:{command.id}",
    )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])
    return SimulationAdjustAck(
        command_id=str(command.id),
        status="accepted",
        simulation_id=simulation.id,
    )


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
    simulation_id: int,
    command_type: str,
    payload_json: dict,
    create_fn: Callable[[TrainerSession], ABCEvent],
) -> TrainerCommandAck:
    user = request.auth
    require_instructor_membership(user)
    idempotency_key = _get_idempotency_key(request)
    correlation_id = _get_correlation_id(request)

    session = _get_session_for_simulation(simulation_id, user)

    command, created = _claim_command(
        session=session,
        command_type=command_type,
        idempotency_key=idempotency_key,
        issued_by=user,
        payload_json=payload_json,
    )
    if not created and command.status == TrainerCommand.CommandStatus.PROCESSED:
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
    "/simulations/{simulation_id}/events/injuries/",
    response=TrainerCommandAck,
    summary="Inject injury event",
)
@api_rate_limit
def create_injury_event(
    request: HttpRequest,
    simulation_id: int,
    body: InjuryCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "injury", **body.model_dump()},
        create_fn=lambda session: _create_injury(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/illnesses/",
    response=TrainerCommandAck,
    summary="Inject illness event",
)
@api_rate_limit
def create_illness_event(
    request: HttpRequest,
    simulation_id: int,
    body: IllnessCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "illness", **body.model_dump()},
        create_fn=lambda session: _create_illness(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/interventions/",
    response=TrainerCommandAck,
    summary="Inject intervention event",
)
@api_rate_limit
def create_intervention_event(
    request: HttpRequest,
    simulation_id: int,
    body: InterventionCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "intervention", **body.model_dump()},
        create_fn=lambda session: _create_intervention(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/vitals/",
    response=TrainerCommandAck,
    summary="Inject vital event",
)
@api_rate_limit
def create_vital_event(
    request: HttpRequest,
    simulation_id: int,
    body: VitalCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "vital", **body.model_dump()},
        create_fn=lambda session: _create_vital(session, body),
    )


@router.get(
    "/simulations/{simulation_id}/events/",
    response=PaginatedResponse[EventEnvelope],
    summary="List TrainerLab runtime events",
)
@api_rate_limit
def list_trainer_events(
    request: HttpRequest,
    simulation_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
    limit: int = Query(default=50, ge=1, le=100),
) -> PaginatedResponse[EventEnvelope]:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)

    queryset = order_outbox_queryset(
        OutboxEvent.objects.filter(
            simulation_id=session.simulation_id,
            event_type__startswith="trainerlab.",
        )
    )

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

        queryset = apply_outbox_cursor(queryset, cursor_event)

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
    "/simulations/{simulation_id}/summary/",
    response=RunSummaryOut,
    summary="Get run summary",
)
@api_rate_limit
def get_run_summary(request: HttpRequest, simulation_id: int) -> RunSummaryOut:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)

    summary = getattr(session, "summary", None)
    if summary is None:
        raise HttpError(404, "Summary not generated")

    return RunSummaryOut(**summary.summary_json)


@router.get(
    "/simulations/{simulation_id}/events/stream/",
    summary="SSE stream for TrainerLab events",
)
def stream_trainer_events(
    request: HttpRequest,
    simulation_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
) -> StreamingHttpResponse:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)

    return stream_outbox_events(
        simulation_id=session.simulation_id,
        cursor=cursor,
        event_type_prefix="trainerlab.",
        sse_event_name="trainerlab",
    )
