"""Feedback endpoints for API v1.

Provides endpoints for submitting and querying user feedback.
Staff endpoints are guarded by is_staff checks.
"""

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
    FeedbackUnreviewedCountOut,
    feedback_to_out,
    feedback_to_staff_out,
)
from apps.common.ratelimit import api_rate_limit
from apps.feedback.services import FeedbackSubmissionError, FeedbackSubmissionService

router = Router(tags=["feedback"], auth=DualAuth())


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
    try:
        fb = FeedbackSubmissionService().submit_feedback(request=request, body=body)
    except FeedbackSubmissionError as err:
        raise HttpError(err.status_code, err.message) from err

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
    "/staff/unreviewed-count/",
    response=FeedbackUnreviewedCountOut,
    summary="[Staff] Unreviewed feedback count",
    description="Staff-only badge/toast count for unreviewed, unarchived feedback.",
)
@api_rate_limit
def staff_unreviewed_count(request: HttpRequest) -> FeedbackUnreviewedCountOut:
    from django.urls import reverse

    from apps.feedback.context_processors import build_unreviewed_feedback_label
    from apps.feedback.models import UserFeedback

    user = request.auth
    if not getattr(user, "is_staff", False):
        raise HttpError(403, "Staff access required")

    count = UserFeedback.objects.filter(is_reviewed=False, is_archived=False).count()
    url = f"{reverse('feedback:staff-list')}?reviewed=unreviewed"
    return FeedbackUnreviewedCountOut(
        count=count,
        label=build_unreviewed_feedback_label(count),
        url=url,
    )


@router.get(
    "/staff/",
    response=FeedbackStaffListResponse,
    summary="[Staff] List all feedback",
    description=(
        "Staff-only endpoint. Returns all feedback with full metadata. "
        "Supports filtering by reviewed, archived, status, category, source, severity, "
        "user_id, simulation_id, lab_type, and ISO 8601 date range."
    ),
)
@api_rate_limit
def staff_list_feedback(
    request: HttpRequest,
    reviewed: str | None = Query(default=None, description="reviewed or unreviewed"),
    archived: str | None = Query(default=None, description="archived or unarchived"),
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

    qs = UserFeedback.objects.select_related(
        "user",
        "simulation",
        "reviewed_by",
        "archived_by",
    ).order_by("-created_at")

    if reviewed in {"reviewed", "true", "1"}:
        qs = qs.filter(is_reviewed=True)
    elif reviewed in {"unreviewed", "false", "0"}:
        qs = qs.filter(is_reviewed=False)
    elif reviewed:
        raise HttpError(400, "Invalid reviewed filter")

    if archived in {"archived", "true", "1"}:
        qs = qs.filter(is_archived=True)
    elif archived in {"unarchived", "false", "0"}:
        qs = qs.filter(is_archived=False)
    elif archived:
        raise HttpError(400, "Invalid archived filter")

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
