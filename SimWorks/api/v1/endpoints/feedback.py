"""Feedback endpoints for API v1.

Provides endpoints for submitting and querying user feedback.
Staff endpoints are guarded by is_staff checks.
"""

from __future__ import annotations

import json

from django.http import HttpRequest
from django.utils.dateparse import parse_datetime
from ninja import Query, Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.feedback import (
    FeedbackCategoryOut,
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackOut,
    FeedbackStaffListResponse,
    feedback_to_out,
    feedback_to_staff_out,
)
from apps.common.ratelimit import api_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["feedback"], auth=DualAuth())

# Maximum serialised size of the client-provided context dict (bytes).
_MAX_CONTEXT_BYTES = 10_240


def _extract_request_metadata(request: HttpRequest) -> dict:
    """Extract grounded request metadata from standard and project headers.

    Returns a flat dict with keys for structured model fields and a
    ``context_meta`` sub-dict suitable for merging into context_json.
    Only reads headers that are present; never invents values.
    """
    headers = request.headers  # Case-insensitive in Django 2.2+
    correlation_id = getattr(request, "correlation_id", None) or ""
    return {
        "request_id": correlation_id,
        "client_platform_raw": headers.get("X-Platform", "").strip().lower(),
        "client_version": headers.get("X-App-Version", "").strip(),
        "os_version": headers.get("X-OS-Version", "").strip(),
        "device_model": headers.get("X-Device-Model", "").strip(),
        "session_identifier": headers.get("X-Session-ID", "").strip(),
        "context_meta": {
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "request_path": request.path,
            "correlation_id": correlation_id,
        },
    }


def _resolve_lab_type(simulation) -> str:
    """Infer lab_type from the guard session tied to a simulation, if available."""
    if simulation is None:
        return ""
    try:
        from apps.guards.models import SessionPresence

        presence = SessionPresence.objects.filter(simulation=simulation).first()
        return presence.lab_type if presence else ""
    except Exception:
        return ""


@router.post(
    "/",
    response={201: FeedbackOut},
    summary="Submit feedback",
    description=(
        "Create a user feedback entry. "
        "Server populates status, source, and all request metadata automatically. "
        "If simulation_id is provided, the user must have access to that simulation. "
        "If conversation_id is provided, access is validated via the conversation's simulation."
    ),
)
@api_rate_limit
def create_feedback(
    request: HttpRequest,
    body: FeedbackCreate,
) -> tuple[int, FeedbackOut]:
    """Submit a new feedback entry."""
    from apps.accounts.context import resolve_request_account
    from apps.accounts.permissions import can_view_simulation
    from apps.feedback.models import UserFeedback

    user = request.auth

    # Body must not be whitespace-only (min_length=1 catches empty string).
    if not body.body.strip():
        raise HttpError(400, "Feedback body cannot be empty or whitespace only")

    # Guard against oversized context payloads.
    if body.context is not None:
        try:
            context_size = len(json.dumps(body.context))
        except (TypeError, ValueError) as err:
            raise HttpError(400, "Context must be a JSON-serialisable object") from err
        if context_size > _MAX_CONTEXT_BYTES:
            raise HttpError(400, "Context payload exceeds the maximum allowed size")

    # Account — nullable; best-effort resolution.
    account = resolve_request_account(request, user=user)

    # ── Simulation access check ───────────────────────────────────────
    simulation = None
    if body.simulation_id is not None:
        from apps.simcore.models import Simulation

        try:
            simulation = Simulation.objects.select_related("account").get(pk=body.simulation_id)
        except Simulation.DoesNotExist as err:
            raise HttpError(404, "Simulation not found") from err
        if not can_view_simulation(user, simulation):
            raise HttpError(403, "You do not have access to this simulation")

    # ── Conversation validation ───────────────────────────────────────
    # Always load and check access via the conversation's own simulation,
    # regardless of whether simulation_id was also provided.
    conversation = None
    if body.conversation_id is not None:
        from apps.simcore.models import Conversation

        try:
            conversation = Conversation.objects.select_related("simulation__account").get(
                pk=body.conversation_id
            )
        except Conversation.DoesNotExist as err:
            raise HttpError(404, "Conversation not found") from err

        if not can_view_simulation(user, conversation.simulation):
            raise HttpError(403, "You do not have access to this conversation's simulation")

        # When both IDs are given, enforce they refer to the same simulation.
        if simulation is not None and conversation.simulation_id != simulation.pk:
            raise HttpError(
                400,
                "Conversation does not belong to the specified simulation",
            )

        # Inherit simulation from the conversation when simulation_id was omitted.
        if simulation is None:
            simulation = conversation.simulation

    # ── Extract and populate structured metadata ──────────────────────
    metadata = _extract_request_metadata(request)

    # Normalise raw platform string to a known choice; fall back to UNKNOWN.
    _valid_platforms = {v for v, _ in UserFeedback.ClientPlatform.choices}
    client_platform = (
        metadata["client_platform_raw"]
        if metadata["client_platform_raw"] in _valid_platforms
        else UserFeedback.ClientPlatform.UNKNOWN
    )

    # Merge server metadata with any client-supplied context.
    merged_context: dict = {**metadata["context_meta"], **(body.context or {})}

    # Infer lab_type from guard session when simulation is linked.
    lab_type = _resolve_lab_type(simulation)

    fb = UserFeedback(
        user=user,
        account=account,
        simulation=simulation,
        conversation=conversation,
        lab_type=lab_type,
        category=body.category,
        source=UserFeedback.Source.IN_APP,
        status=UserFeedback.Status.NEW,
        title=(body.title or "").strip(),
        body=body.body.strip(),
        rating=body.rating,
        allow_follow_up=body.allow_follow_up,
        # Structured metadata fields populated from request context.
        request_id=metadata["request_id"],
        client_platform=client_platform,
        client_version=metadata["client_version"],
        os_version=metadata["os_version"],
        device_model=metadata["device_model"],
        session_identifier=metadata["session_identifier"],
        context_json=merged_context,
    )
    fb.save()

    logger.info(
        "feedback.submitted",
        feedback_id=fb.pk,
        user_id=user.pk,
        category=fb.category,
        simulation_id=getattr(simulation, "pk", None),
    )

    return 201, feedback_to_out(fb)


@router.get(
    "/categories/",
    response=list[FeedbackCategoryOut],
    auth=None,
    summary="List feedback categories",
    description="Returns the allowed feedback category choices.",
)
def list_categories(request: HttpRequest) -> list[FeedbackCategoryOut]:
    from apps.feedback.models import UserFeedback

    return [FeedbackCategoryOut(value=v, label=l) for v, l in UserFeedback.Category.choices]  # noqa: E741


@router.get(
    "/me/",
    response=FeedbackListResponse,
    summary="My feedback submissions",
    description="Returns the authenticated user's recent feedback submissions, newest first.",
)
@api_rate_limit
def my_feedback(
    request: HttpRequest,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> FeedbackListResponse:
    from apps.feedback.models import UserFeedback

    user = request.auth
    qs = UserFeedback.objects.filter(user=user).order_by("-created_at")
    total = qs.count()
    page = list(qs[offset : offset + limit])
    return FeedbackListResponse(
        items=[feedback_to_out(fb) for fb in page],
        count=len(page),
        total=total,
    )


@router.get(
    "/staff/",
    response=FeedbackStaffListResponse,
    summary="[Staff] List all feedback",
    description=(
        "Staff-only endpoint. Returns all feedback with full metadata. "
        "Supports filtering by status, category, source, severity, "
        "user_id, simulation_id, lab_type, and ISO 8601 date range."
    ),
)
@api_rate_limit
def staff_list_feedback(
    request: HttpRequest,
    status: str | None = Query(default=None, description="Filter by status"),
    category: str | None = Query(default=None, description="Filter by category"),
    source: str | None = Query(default=None, description="Filter by source"),
    severity: str | None = Query(default=None, description="Filter by severity"),
    client_platform: str | None = Query(default=None, description="Filter by client platform"),
    user_id: int | None = Query(default=None, description="Filter by user ID"),
    simulation_id: int | None = Query(default=None, description="Filter by simulation ID"),
    lab_type: str | None = Query(default=None, description="Filter by lab type"),
    date_from: str | None = Query(default=None, description="ISO 8601 start datetime (inclusive)"),
    date_to: str | None = Query(default=None, description="ISO 8601 end datetime (inclusive)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackStaffListResponse:
    from apps.feedback.models import UserFeedback

    user = request.auth
    if not getattr(user, "is_staff", False):
        raise HttpError(403, "Staff access required")

    qs = UserFeedback.objects.select_related("user", "simulation", "resolved_by").order_by(
        "-created_at"
    )

    if status:
        qs = qs.filter(status=status)
    if category:
        qs = qs.filter(category=category)
    if source:
        qs = qs.filter(source=source)
    if severity:
        qs = qs.filter(severity=severity)
    if client_platform:
        qs = qs.filter(client_platform=client_platform)
    if user_id is not None:
        qs = qs.filter(user_id=user_id)
    if simulation_id is not None:
        qs = qs.filter(simulation_id=simulation_id)
    if lab_type:
        qs = qs.filter(lab_type=lab_type)

    if date_from is not None:
        dt_from = parse_datetime(date_from)
        if dt_from is None:
            raise HttpError(400, "Invalid date_from; expected ISO 8601 datetime")
        qs = qs.filter(created_at__gte=dt_from)

    if date_to is not None:
        dt_to = parse_datetime(date_to)
        if dt_to is None:
            raise HttpError(400, "Invalid date_to; expected ISO 8601 datetime")
        qs = qs.filter(created_at__lte=dt_to)

    total = qs.count()
    page = list(qs[offset : offset + limit])
    return FeedbackStaffListResponse(
        items=[feedback_to_staff_out(fb) for fb in page],
        count=len(page),
        total=total,
    )
