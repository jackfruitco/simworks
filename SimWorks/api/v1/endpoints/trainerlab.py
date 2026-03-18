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
    AnnotationCreateIn,
    AnnotationOut,
    AssessmentFindingCreateIn,
    ControlPlaneDebugOut,
    DiagnosticResultCreateIn,
    DictionaryItemOut,
    DispositionStateCreateIn,
    IllnessCreateIn,
    InjuryCreateIn,
    InterventionCreateIn,
    InterventionDictionaryItemOut,
    LabAccessOut,
    PresetApplyDiff,
    PresetApplyOut,
    ProblemCreateIn,
    ProblemStatusOut,
    ProblemStatusUpdateIn,
    ResourceStateCreateIn,
    RunSummaryOut,
    ScenarioBriefDetailOut,
    ScenarioBriefUpdateIn,
    ScenarioInstructionApplyIn,
    ScenarioInstructionCreateIn,
    ScenarioInstructionOut,
    ScenarioInstructionPermissionIn,
    ScenarioInstructionPermissionOut,
    ScenarioInstructionUnshareIn,
    ScenarioInstructionUpdateIn,
    SimulationAdjustAck,
    SimulationAdjustIn,
    SimulationNoteCreateIn,
    SteerPromptIn,
    TrainerCommandAck,
    TrainerRunOut,
    TrainerRuntimeStateOut,
    TrainerSessionCreateIn,
    VitalCreateIn,
    annotation_to_out,
    control_plane_debug_to_out,
    scenario_instruction_to_out,
    scenario_permission_to_out,
    trainer_run_to_out,
    trainer_state_to_out,
)
from api.v1.sse import stream_outbox_events
from apps.common.models import OutboxEvent
from apps.common.outbox.outbox import apply_outbox_cursor, order_outbox_queryset
from apps.common.ratelimit import api_rate_limit
from apps.simcore.models import Simulation
from apps.trainerlab.access import require_instructor_membership
from apps.trainerlab.adjudication import adjudicate_intervention
from apps.trainerlab.diagnostic_dictionary import get_diagnostic_definition
from apps.trainerlab.finding_dictionary import get_finding_definition
from apps.trainerlab.injury_dictionary import get_injury_dictionary_choices
from apps.trainerlab.intervention_dictionary import (
    list_intervention_definitions,
    normalize_site_code,
)
from apps.trainerlab.models import (
    ETCO2,
    SPO2,
    AssessmentFinding,
    BloodGlucoseLevel,
    BloodPressure,
    DiagnosticResult,
    DispositionState,
    EventSource,
    HeartRate,
    Illness,
    Injury,
    Intervention,
    Problem,
    ResourceState,
    RespiratoryRate,
    ScenarioInstruction,
    ScenarioInstructionPermission,
    SessionStatus,
    SimulationNote,
    TrainerCommand,
    TrainerSession,
)
from apps.trainerlab.services import (
    append_pending_runtime_reason,
    commit_non_ai_mutation_side_effects,
    compute_preset_diff,
    create_debrief_annotation,
    create_session_with_initial_generation,
    deactivate_domain_object,
    emit_domain_runtime_event,
    emit_runtime_event,
    enqueue_vitals_progression,
    get_or_create_command,
    get_session_annotations,
    pause_session,
    refresh_completed_run_review,
    resume_session,
    snapshot_before_preset,
    start_session,
    stop_session,
    trigger_manual_tick,
    update_problem_status,
    update_scenario_brief,
)

router = Router(tags=["trainerlab"], auth=JWTAuth())
UserModel = get_user_model()


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


def _reject_terminal_mutation(
    *,
    command: TrainerCommand,
    session: TrainerSession,
    allow_post_stop_note: bool = False,
) -> None:
    if session.status == SessionStatus.COMPLETED and allow_post_stop_note:
        return

    if session.status == SessionStatus.COMPLETED:
        error = "Simulation is completed; only notes may be added."
    elif session.status == SessionStatus.FAILED:
        error = "Simulation has failed; no further changes are allowed."
    else:
        return

    command.status = TrainerCommand.CommandStatus.FAILED
    command.error = error
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "error", "processed_at"])
    raise HttpError(409, error)


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
    response=list[InterventionDictionaryItemOut],
    summary="List intervention dictionary (iOS-compatible flat format)",
)
@api_rate_limit
def intervention_dictionary(request: HttpRequest) -> list[InterventionDictionaryItemOut]:
    user = request.auth
    require_instructor_membership(user)
    return [
        InterventionDictionaryItemOut(
            intervention_type=defn.type_code,
            label=defn.label,
            sites=[
                DictionaryItemOut(code=normalize_site_code(code), label=label)
                for code, label in defn.sites
            ],
        )
        for defn in list_intervention_definitions()
    ]


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
    response=PresetApplyOut,
    summary="Apply preset instructions to a TrainerLab simulation",
)
@api_rate_limit
def apply_preset(
    request: HttpRequest,
    preset_id: int,
    body: ScenarioInstructionApplyIn,
) -> PresetApplyOut:
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
        return PresetApplyOut(command_id=str(command.id), status="accepted")
    _reject_terminal_mutation(command=command, session=session)

    # #5: Snapshot state before applying preset to compute diff afterwards
    before_snapshot = snapshot_before_preset(session)

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
        event_type="preset.applied",
        payload={
            "preset_id": instruction.id,
            "title": instruction.title,
        },
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=(f"preset.applied:{session.id}:{instruction.id}:{command.id}"),
    )
    append_pending_runtime_reason(
        session=session,
        reason_kind="preset_applied",
        payload={
            "preset_id": instruction.id,
            "title": instruction.title,
            "command_id": str(command.id),
        },
        correlation_id=correlation_id,
    )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])

    # #5: Compute diff and return enriched response
    diff_data = compute_preset_diff(before=before_snapshot, session=session)
    diff = PresetApplyDiff(
        causes_added=diff_data.get("causes_added", []),
        vitals_changed={
            vtype: {"before": v.get("before"), "after": v["after"]}
            for vtype, v in diff_data.get("vitals_changed", {}).items()
        },
        state_revision_before=diff_data.get("state_revision_before"),
    )
    return PresetApplyOut(command_id=str(command.id), status="accepted", diff=diff)


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


@router.get(
    "/simulations/{simulation_id}/state/",
    response=TrainerRuntimeStateOut,
    summary="Get authoritative TrainerLab runtime state snapshot",
)
@api_rate_limit
def get_trainer_runtime_state(request: HttpRequest, simulation_id: int) -> TrainerRuntimeStateOut:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    return trainer_state_to_out(session)


@router.get(
    "/simulations/{simulation_id}/control-plane/",
    response=ControlPlaneDebugOut,
    summary="Get TrainerLab control-plane debug state",
)
@api_rate_limit
def get_control_plane_debug(request: HttpRequest, simulation_id: int) -> ControlPlaneDebugOut:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    return control_plane_debug_to_out(session)


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
    _reject_terminal_mutation(command=command, session=session)

    state = dict(session.runtime_state_json or {})
    prompts = list(state.get("steering_prompts", []))
    prompts.append(body.prompt)
    state["steering_prompts"] = prompts
    state["last_instruction"] = body.prompt
    session.runtime_state_json = state
    session.save(update_fields=["runtime_state_json", "modified_at"])

    emit_runtime_event(
        session=session,
        event_type="command.accepted",
        payload={
            "command": "steer_prompt",
            "prompt": body.prompt,
        },
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"command.accepted:{command.id}",
    )
    append_pending_runtime_reason(
        session=session,
        reason_kind="steer_prompt",
        payload={
            "command_id": str(command.id),
            "prompt": body.prompt,
        },
        correlation_id=correlation_id,
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
    _reject_terminal_mutation(command=command, session=session)

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
        event_type="adjustment.accepted",
        payload=adjustment_entry,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"adjustment.accepted:{command.id}",
    )
    emit_runtime_event(
        session=session,
        event_type="adjustment.applied",
        payload=adjustment_entry,
        created_by=user,
        correlation_id=correlation_id,
        idempotency_key=f"adjustment.applied:{command.id}",
    )
    append_pending_runtime_reason(
        session=session,
        reason_kind="adjustment",
        payload=adjustment_entry,
        correlation_id=correlation_id,
    )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])
    return SimulationAdjustAck(
        command_id=str(command.id),
        status="accepted",
        simulation_id=simulation.id,
    )


def _resolve_superseded_intervention(
    *,
    simulation_id: int,
    supersedes_event_id: int | None,
) -> Intervention | None:
    if not supersedes_event_id:
        return None
    return Intervention.objects.filter(pk=supersedes_event_id, simulation_id=simulation_id).first()


def _problem_identity_from_context(
    *, march_category: str, label: str, fallback: str
) -> dict[str, str]:
    kind = {
        "M": "hemorrhage",
        "A": "airway_obstruction",
        "R": "respiratory_distress",
        "H1": "heat_illness",
    }.get(march_category, fallback)
    return {
        "kind": kind,
        "code": kind,
        "title": label,
        "display_name": label,
    }


def _create_injury(session: TrainerSession, body: InjuryCreateIn) -> Injury:
    old_injury: Injury | None = None
    if body.supersedes_event_id:
        old_injury = Injury.objects.filter(
            pk=body.supersedes_event_id,
            simulation=session.simulation,
        ).first()

    new_injury = Injury.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=old_injury,
        injury_location=body.injury_location,
        injury_kind=body.injury_kind,
        injury_description=body.injury_description,
        description=body.description,
        metadata_json=body.metadata,
    )
    new_injury._deactivated_objects = [old_injury] if old_injury else []
    return new_injury


def _create_illness(session: TrainerSession, body: IllnessCreateIn) -> Illness:
    old_illness: Illness | None = None
    if body.supersedes_event_id:
        old_illness = Illness.objects.filter(
            pk=body.supersedes_event_id,
            simulation=session.simulation,
        ).first()

    new_illness = Illness.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=old_illness,
        name=body.name,
        description=body.description,
        anatomical_location=body.anatomical_location,
        laterality=body.laterality,
        metadata_json=body.metadata,
    )
    new_illness._deactivated_objects = [old_illness] if old_illness else []
    return new_illness


def _create_problem(session: TrainerSession, body: ProblemCreateIn) -> Problem:
    old_problem: Problem | None = None
    if body.supersedes_event_id:
        old_problem = (
            Problem.objects.select_related("cause_injury", "cause_illness")
            .filter(pk=body.supersedes_event_id, simulation=session.simulation)
            .first()
        )

    cause_injury: Injury | None = None
    cause_illness: Illness | None = None
    if body.cause_kind == "injury":
        cause_injury = Injury.objects.filter(
            pk=body.cause_id,
            simulation=session.simulation,
            is_active=True,
        ).first()
        if cause_injury is None:
            raise ValidationError(
                {"cause_id": "Active injury cause not found for this simulation."}
            )
    else:
        cause_illness = Illness.objects.filter(
            pk=body.cause_id,
            simulation=session.simulation,
            is_active=True,
        ).first()
        if cause_illness is None:
            raise ValidationError(
                {"cause_id": "Active illness cause not found for this simulation."}
            )

    parent_problem = None
    if body.parent_problem_id:
        parent_problem = (
            Problem.objects.select_related("cause_injury", "cause_illness")
            .filter(
                pk=body.parent_problem_id,
                simulation=session.simulation,
                is_active=True,
            )
            .first()
        )
        if parent_problem is None:
            raise ValidationError(
                {"parent_problem_id": "Active parent problem not found for this simulation."}
            )

    created = Problem.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=old_problem,
        cause_injury=cause_injury,
        cause_illness=cause_illness,
        parent_problem=parent_problem,
        problem_kind=(
            Problem.ProblemKind.INJURY
            if body.cause_kind == "injury"
            else Problem.ProblemKind.ILLNESS
        ),
        kind=body.kind,
        code=body.code or body.kind,
        slug="",
        title=body.title,
        display_name=body.display_name or body.title,
        description=body.description,
        march_category=body.march_category,
        severity=body.severity,
        anatomical_location=body.anatomical_location,
        laterality=body.laterality,
        status=body.status,
        metadata_json=body.metadata,
    )
    created._deactivated_objects = [old_problem] if old_problem else []
    return created


def _create_assessment_finding(
    session: TrainerSession, body: AssessmentFindingCreateIn
) -> AssessmentFinding:
    definition = get_finding_definition(body.finding_kind)
    supersedes = (
        AssessmentFinding.objects.filter(
            pk=body.supersedes_event_id,
            simulation=session.simulation,
        ).first()
        if body.supersedes_event_id
        else None
    )
    target_problem = (
        Problem.objects.filter(
            pk=body.target_problem_id,
            simulation=session.simulation,
            is_active=True,
        ).first()
        if body.target_problem_id
        else None
    )
    obj = AssessmentFinding.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=supersedes,
        target_problem=target_problem,
        kind=definition.kind,
        code=definition.code,
        slug="",
        title=body.title or definition.title,
        display_name=body.title or definition.title,
        description=body.description,
        status=body.status,
        severity=body.severity,
        anatomical_location=body.anatomical_location,
        laterality=body.laterality,
        metadata_json=body.metadata,
    )
    obj._deactivated_objects = [supersedes] if supersedes else []
    return obj


def _create_diagnostic_result(
    session: TrainerSession, body: DiagnosticResultCreateIn
) -> DiagnosticResult:
    definition = get_diagnostic_definition(body.diagnostic_kind)
    supersedes = (
        DiagnosticResult.objects.filter(
            pk=body.supersedes_event_id,
            simulation=session.simulation,
        ).first()
        if body.supersedes_event_id
        else None
    )
    target_problem = (
        Problem.objects.filter(
            pk=body.target_problem_id,
            simulation=session.simulation,
            is_active=True,
        ).first()
        if body.target_problem_id
        else None
    )
    obj = DiagnosticResult.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=supersedes,
        target_problem=target_problem,
        kind=definition.kind,
        code=definition.code,
        slug="",
        title=body.title or definition.title,
        display_name=body.title or definition.title,
        description=body.description,
        status=body.status,
        value_text=body.value_text,
        metadata_json=body.metadata,
    )
    obj._deactivated_objects = [supersedes] if supersedes else []
    return obj


def _create_resource_state(session: TrainerSession, body: ResourceStateCreateIn) -> ResourceState:
    supersedes = (
        ResourceState.objects.filter(
            pk=body.supersedes_event_id,
            simulation=session.simulation,
        ).first()
        if body.supersedes_event_id
        else None
    )
    obj = ResourceState.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=supersedes,
        kind=body.kind,
        code=body.code or body.kind,
        slug="",
        title=body.title,
        display_name=body.display_name or body.title,
        status=body.status,
        quantity_available=body.quantity_available,
        quantity_unit=body.quantity_unit,
        description=body.description,
        metadata_json=body.metadata,
    )
    obj._deactivated_objects = [supersedes] if supersedes else []
    return obj


def _create_disposition_state(
    session: TrainerSession, body: DispositionStateCreateIn
) -> DispositionState:
    supersedes = (
        DispositionState.objects.filter(
            pk=body.supersedes_event_id,
            simulation=session.simulation,
            is_active=True,
        ).first()
        if body.supersedes_event_id
        else DispositionState.objects.filter(simulation=session.simulation, is_active=True)
        .order_by("-timestamp", "-id")
        .first()
    )
    obj = DispositionState.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=supersedes,
        status=body.status,
        transport_mode=body.transport_mode,
        destination=body.destination,
        eta_minutes=body.eta_minutes,
        handoff_ready=body.handoff_ready,
        scene_constraints_json=body.scene_constraints,
        metadata_json=body.metadata,
    )
    obj._deactivated_objects = [supersedes] if supersedes else []
    return obj


def _create_intervention(session: TrainerSession, body: InterventionCreateIn) -> Intervention:
    supersedes = _resolve_superseded_intervention(
        simulation_id=session.simulation_id,
        supersedes_event_id=body.supersedes_event_id,
    )

    obj = Intervention(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        supersedes=supersedes,
        intervention_type=body.intervention_type,
        site_code=body.site_code,
        target_problem_id=body.target_problem_id,
        status=body.status,
        effectiveness=body.effectiveness,
        notes=body.notes,
        details_json=body.details.model_dump(exclude_none=True),
        initiated_by_type=body.initiated_by_type,
        initiated_by_id=body.initiated_by_id,
    )
    obj.save()
    obj._deactivated_objects = [supersedes] if supersedes else []
    obj._adjudication_result = adjudicate_intervention(obj)
    return obj


def _create_note(session: TrainerSession, body: SimulationNoteCreateIn) -> SimulationNote:
    return SimulationNote.objects.create(
        simulation=session.simulation,
        source=EventSource.INSTRUCTOR,
        content=body.content,
    )


_VITAL_MODEL_MAP = {
    "heart_rate": HeartRate,
    "respiratory_rate": RespiratoryRate,
    "spo2": SPO2,
    "etco2": ETCO2,
    "blood_glucose": BloodGlucoseLevel,
    "blood_pressure": BloodPressure,
}


def _create_vital(session: TrainerSession, body: VitalCreateIn) -> Any:
    vital_model = _VITAL_MODEL_MAP.get(body.vital_type)
    supersedes = (
        vital_model.objects.filter(
            pk=body.supersedes_event_id, simulation_id=session.simulation_id
        ).first()
        if body.supersedes_event_id and vital_model
        else None
    )
    if supersedes is not None and supersedes.is_active:
        supersedes.is_active = False
        supersedes.save(update_fields=["is_active"])

    common = {
        "simulation": session.simulation,
        "source": EventSource.INSTRUCTOR,
        "supersedes": supersedes,
        "min_value": body.min_value,
        "max_value": body.max_value,
        "lock_value": body.lock_value,
    }

    if body.vital_type == "heart_rate":
        return HeartRate.objects.create(**common)
    if body.vital_type == "respiratory_rate":
        return RespiratoryRate.objects.create(**common)
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
    create_fn: Callable[[TrainerSession], Any],
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
    event_kind = payload_json.get("event_kind")
    _reject_terminal_mutation(
        command=command,
        session=session,
        allow_post_stop_note=event_kind == "note",
    )

    try:
        domain_event = create_fn(session)
    except ValidationError as exc:
        _mark_command_failed(command, str(exc))
        raise HttpError(409, str(exc)) from None

    event_type = {
        "injury": "injury.created",
        "illness": "illness.created",
        "problem": "problem.created",
        "assessment_finding": "trainerlab.assessment_finding.created",
        "diagnostic_result": "trainerlab.diagnostic_result.created",
        "resource": "trainerlab.resource.updated",
        "disposition": "trainerlab.disposition.updated",
        "intervention": "intervention.created",
        "note": "note.created",
        "vital": "trainerlab.vital.updated",
    }.get(event_kind, "event.created")

    send_to_ai = bool(payload_json.get("send_to_ai", False))
    from apps.trainerlab.event_payloads import serialize_domain_event

    if event_kind == "note":
        event_payload = {
            "domain_event_id": domain_event.id,
            "domain_event_type": domain_event.__class__.__name__,
            "source": domain_event.source,
            "timestamp": domain_event.timestamp.astimezone(UTC).isoformat(),
            "supersedes_event_id": domain_event.supersedes_id,
            "content": getattr(domain_event, "content", ""),
            "created_by_role": payload_json.get("performed_by_role", "instructor"),
        }
    else:
        event_payload = serialize_domain_event(domain_event)

    for deactivated in getattr(domain_event, "_deactivated_objects", []):
        deactivate_domain_object(
            session=session,
            obj=deactivated,
            correlation_id=correlation_id,
            created_by=user,
            action="superseded",
        )

    if event_kind in {
        "injury",
        "illness",
        "problem",
        "assessment_finding",
        "diagnostic_result",
        "resource",
        "disposition",
        "intervention",
    }:
        emit_domain_runtime_event(
            session=session,
            event_type=event_type,
            obj=domain_event,
            created_by=user,
            correlation_id=correlation_id,
            idempotency_key=f"{event_type}:{domain_event.id}",
        )
    elif event_kind == "note":
        emit_runtime_event(
            session=session,
            event_type=event_type,
            payload=event_payload,
            created_by=user,
            correlation_id=correlation_id,
            idempotency_key=f"{event_type}:{domain_event.id}",
        )
    else:
        emit_runtime_event(
            session=session,
            event_type=event_type,
            payload=event_payload,
            created_by=user,
            correlation_id=correlation_id,
            idempotency_key=f"{event_type}:{domain_event.id}",
        )

    if event_kind == "intervention" and getattr(domain_event, "_adjudication_result", None):
        adjudication_result = domain_event._adjudication_result
        refreshed_problem = Problem.objects.filter(pk=domain_event.target_problem_id).first()
        if refreshed_problem is not None and adjudication_result.changed:
            emit_domain_runtime_event(
                session=session,
                event_type=(
                    "problem.resolved"
                    if refreshed_problem.status == Problem.Status.RESOLVED
                    else "problem.updated"
                ),
                obj=refreshed_problem,
                created_by=user,
                correlation_id=correlation_id,
                idempotency_key=f"problem.updated:post-intervention:{refreshed_problem.id}:{domain_event.id}",
            )
    commit_non_ai_mutation_side_effects(
        session=session,
        event_kind=event_kind,
        correlation_id=correlation_id,
        worker_kind="manual_injection",
        domains=[event_kind],
    )

    should_queue_runtime = session.status != SessionStatus.COMPLETED and (
        event_kind != "note" or send_to_ai
    )
    if should_queue_runtime:
        runtime_reason_payload = {
            "command_id": str(command.id),
            "domain_event_id": domain_event.id,
            "domain_event_type": domain_event.__class__.__name__,
            "event_kind": event_kind,
        }
        if event_kind == "note":
            runtime_reason_payload.update(
                {
                    "note_id": domain_event.id,
                    "content": getattr(domain_event, "content", ""),
                    "send_to_ai": send_to_ai,
                }
            )
        append_pending_runtime_reason(
            session=session,
            reason_kind=f"{event_kind}_recorded",
            payload=runtime_reason_payload,
            correlation_id=correlation_id,
        )

    command.status = TrainerCommand.CommandStatus.PROCESSED
    command.processed_at = timezone.now()
    command.save(update_fields=["status", "processed_at"])
    if event_kind == "note" and session.status == SessionStatus.COMPLETED:
        refresh_completed_run_review(session=session, generated_by=user)
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
    "/simulations/{simulation_id}/events/problems/",
    response=TrainerCommandAck,
    summary="Inject problem event",
)
@api_rate_limit
def create_problem_event(
    request: HttpRequest,
    simulation_id: int,
    body: ProblemCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "problem", **body.model_dump()},
        create_fn=lambda session: _create_problem(session, body),
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
    "/simulations/{simulation_id}/events/assessment-findings/",
    response=TrainerCommandAck,
    summary="Inject assessment finding event",
)
@api_rate_limit
def create_assessment_finding_event(
    request: HttpRequest,
    simulation_id: int,
    body: AssessmentFindingCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "assessment_finding", **body.model_dump()},
        create_fn=lambda session: _create_assessment_finding(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/diagnostic-results/",
    response=TrainerCommandAck,
    summary="Inject diagnostic result event",
)
@api_rate_limit
def create_diagnostic_result_event(
    request: HttpRequest,
    simulation_id: int,
    body: DiagnosticResultCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "diagnostic_result", **body.model_dump()},
        create_fn=lambda session: _create_diagnostic_result(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/resources/",
    response=TrainerCommandAck,
    summary="Inject resource state event",
)
@api_rate_limit
def create_resource_event(
    request: HttpRequest,
    simulation_id: int,
    body: ResourceStateCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "resource", **body.model_dump()},
        create_fn=lambda session: _create_resource_state(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/disposition/",
    response=TrainerCommandAck,
    summary="Inject disposition state event",
)
@api_rate_limit
def create_disposition_event(
    request: HttpRequest,
    simulation_id: int,
    body: DispositionStateCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "disposition", **body.model_dump()},
        create_fn=lambda session: _create_disposition_state(session, body),
    )


@router.post(
    "/simulations/{simulation_id}/events/notes/",
    response=TrainerCommandAck,
    summary="Inject simulation note event",
)
@api_rate_limit
def create_note_event(
    request: HttpRequest,
    simulation_id: int,
    body: SimulationNoteCreateIn,
) -> TrainerCommandAck:
    return _inject_event_core(
        request=request,
        simulation_id=simulation_id,
        command_type=TrainerCommand.CommandType.INJECT_EVENT,
        payload_json={"event_kind": "note", **body.model_dump()},
        create_fn=lambda session: _create_note(session, body),
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
        OutboxEvent.objects.filter(simulation_id=session.simulation_id)
    )

    if cursor:
        try:
            cursor_uuid = uuid.UUID(cursor)
        except ValueError:
            raise HttpError(400, "Invalid cursor format") from None

        cursor_event = OutboxEvent.objects.filter(
            id=cursor_uuid,
            simulation_id=session.simulation_id,
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
async def stream_trainer_events(
    request: HttpRequest,
    simulation_id: int,
    cursor: str | None = Query(default=None, description="Outbox event cursor UUID"),
) -> StreamingHttpResponse:
    from asgiref.sync import sync_to_async

    user = request.auth
    await sync_to_async(require_instructor_membership)(user)
    session = await sync_to_async(_get_session_for_simulation)(simulation_id, user)

    return stream_outbox_events(
        simulation_id=session.simulation_id,
        cursor=cursor,
        sse_event_name="sim",
        heartbeat_interval_seconds=10.0,
        poll_interval_seconds=1.0,
        heartbeat_comment=": keep-alive\n\n",
    )


# ---------------------------------------------------------------------------
# #1 — Orca Pulse Vitals tick endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/simulations/{simulation_id}/run/tick/vitals/",
    response=TrainerCommandAck,
    summary="Trigger an on-demand AI vital signs progression update",
)
@api_rate_limit
def trigger_vitals_tick(
    request: HttpRequest,
    simulation_id: int,
) -> TrainerCommandAck:
    """
    Immediately enqueue a vitals-only AI progression turn.

    Unlike the full runtime tick, this service only updates vital sign ranges
    and does not modify causes, problems, or interventions.
    """
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    correlation_id = _get_correlation_id(request)

    if session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED}:
        raise HttpError(409, "Vitals tick is only allowed on running or paused sessions.")

    call_id = enqueue_vitals_progression(session=session, correlation_id=correlation_id)
    if call_id is None:
        raise HttpError(503, "Could not enqueue vitals progression; please retry.")

    return TrainerCommandAck(command_id=call_id, status="accepted")


# ---------------------------------------------------------------------------
# #2 — Problem status mutation
# ---------------------------------------------------------------------------


@router.patch(
    "/simulations/{simulation_id}/problems/{problem_id}/",
    response=ProblemStatusOut,
    summary="Update treatment/resolution state of a problem",
)
@api_rate_limit
def update_problem(
    request: HttpRequest,
    simulation_id: int,
    problem_id: int,
    body: ProblemStatusUpdateIn,
) -> ProblemStatusOut:
    """
    Set the instructor-controlled treatment or resolution state of a Problem.
    """
    from django.core.exceptions import ValidationError as DjangoValidationError

    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    correlation_id = _get_correlation_id(request)

    try:
        problem = update_problem_status(
            session=session,
            problem_id=problem_id,
            is_treated=body.is_treated,
            is_resolved=body.is_resolved,
            correlation_id=correlation_id,
        )
    except DjangoValidationError as exc:
        raise HttpError(404, str(exc)) from None

    return ProblemStatusOut(
        problem_id=problem.id,
        is_treated=problem.is_treated,
        is_controlled=problem.is_controlled,
        is_resolved=problem.is_resolved,
        status=problem.status,
        label=problem.display_name or problem.title,
    )


# ---------------------------------------------------------------------------
# #3 — Manual tick trigger
# ---------------------------------------------------------------------------


@router.post(
    "/simulations/{simulation_id}/run/tick/",
    response=TrainerCommandAck,
    summary="Trigger an immediate AI runtime turn",
)
@api_rate_limit
def trigger_tick(
    request: HttpRequest,
    simulation_id: int,
) -> TrainerCommandAck:
    """
    Immediately queue a manual AI runtime turn, bypassing the tick interval timer.

    Useful for teaching moments where the trainer needs an instant patient state update.
    The response is `accepted` once the reason is queued; the actual AI turn executes
    asynchronously.
    """
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    correlation_id = _get_correlation_id(request)

    try:
        reason = trigger_manual_tick(session=session, correlation_id=correlation_id)
    except Exception as exc:
        raise HttpError(409, str(exc)) from None

    return TrainerCommandAck(
        command_id=reason.get("created_at", ""),
        status="accepted",
    )


# ---------------------------------------------------------------------------
# #4 — Live debrief annotations
# ---------------------------------------------------------------------------


@router.post(
    "/simulations/{simulation_id}/annotations/",
    response={201: AnnotationOut},
    summary="Create a live debrief annotation",
)
@api_rate_limit
def create_annotation(
    request: HttpRequest,
    simulation_id: int,
    body: AnnotationCreateIn,
) -> tuple[int, AnnotationOut]:
    """
    Drop a structured pedagogical annotation during a live session.

    Annotations are tied to learning objectives (e.g. hemorrhage_control, airway)
    and outcomes (correct, incorrect, missed). They are included in the AI debrief
    generation context to improve post-session feedback quality.
    """
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    correlation_id = _get_correlation_id(request)

    annotation = create_debrief_annotation(
        session=session,
        created_by=user,
        learning_objective=body.learning_objective,
        observation_text=body.observation_text,
        outcome=body.outcome,
        linked_event_id=body.linked_event_id,
        elapsed_seconds_at=body.elapsed_seconds_at,
        correlation_id=correlation_id,
    )
    return 201, annotation_to_out(annotation)


@router.get(
    "/simulations/{simulation_id}/annotations/",
    response=list[AnnotationOut],
    summary="List debrief annotations for a simulation",
)
@api_rate_limit
def list_annotations(
    request: HttpRequest,
    simulation_id: int,
) -> list[AnnotationOut]:
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    return [annotation_to_out(a) for a in get_session_annotations(session=session)]


# ---------------------------------------------------------------------------
# #7 — Scenario brief edit
# ---------------------------------------------------------------------------


@router.patch(
    "/simulations/{simulation_id}/scenario-brief/",
    response=ScenarioBriefDetailOut,
    summary="Edit the scenario brief for a simulation",
)
@api_rate_limit
def update_scenario_brief_endpoint(
    request: HttpRequest,
    simulation_id: int,
    body: ScenarioBriefUpdateIn,
) -> ScenarioBriefDetailOut:
    """
    Partially update the AI-generated scenario brief.

    Only the fields provided in the request body are changed; all others retain
    their current values. This is useful for correcting or customising the
    read-aloud brief before delivering it to students.

    Emits a `trainerlab.scenario_brief.updated` SSE event.
    """
    user = request.auth
    require_instructor_membership(user)
    session = _get_session_for_simulation(simulation_id, user)
    correlation_id = _get_correlation_id(request)

    brief = update_scenario_brief(
        session=session,
        updates=body.model_dump(exclude_none=True),
        user=user,
        correlation_id=correlation_id,
    )
    return ScenarioBriefDetailOut(
        domain_event_id=brief.id,
        read_aloud_brief=brief.read_aloud_brief,
        environment=brief.environment,
        location_overview=brief.location_overview,
        threat_context=brief.threat_context,
        evacuation_options=list(brief.evacuation_options or []),
        evacuation_time=brief.evacuation_time,
        special_considerations=list(brief.special_considerations or []),
    )
