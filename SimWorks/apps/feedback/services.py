from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
import json
from typing import ClassVar

from django.core.exceptions import DisallowedHost
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.common.emailing.service import send_templated_email
from config.logging import get_logger

from .models import FeedbackAuditEvent, FeedbackRemark, UserFeedback

logger = get_logger(__name__)

FEEDBACK_NOTIFICATION_RECIPIENT = "feedback@jackfruitco.com"
FEEDBACK_NOTIFICATION_FROM_EMAIL = "noreply@jackfruitco.com"
FEEDBACK_BODY_PREVIEW_LENGTH = 400
MAX_CONTEXT_BYTES = 10_240


@dataclass
class FeedbackSubmissionError(Exception):
    status_code: int
    message: str


def _extract_request_metadata(request: HttpRequest) -> dict:
    """Extract request metadata from the mobile feedback headers."""
    headers = request.headers
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
    if simulation is None:
        return ""
    try:
        from apps.guards.models import SessionPresence

        presence = SessionPresence.objects.filter(simulation=simulation).first()
        return presence.lab_type if presence else ""
    except Exception:
        logger.debug(
            "feedback.resolve_lab_type_failed", simulation_id=getattr(simulation, "pk", None)
        )
        return ""


def _feedback_actor_label(user) -> str:
    if not user:
        return "Unknown user"
    name = getattr(user, "get_full_name", lambda: "")()
    email = getattr(user, "email", "") or ""
    return f"{name} <{email}>" if name and email else name or email or f"User {user.pk}"


def build_staff_feedback_detail_url(
    feedback: UserFeedback, request: HttpRequest | None = None
) -> str:
    path = reverse("feedback:staff-detail", args=[feedback.pk])
    if request is not None:
        try:
            return request.build_absolute_uri(path)
        except DisallowedHost:
            logger.warning("feedback.detail_url_disallowed_host", feedback_id=feedback.pk)

    from apps.common.emailing.environment import get_email_base_url

    return f"{get_email_base_url()}{path}"


def build_staff_unreviewed_feedback_url(request: HttpRequest | None = None) -> str:
    path = f"{reverse('feedback:staff-list')}?reviewed=unreviewed"
    if request is not None:
        try:
            return request.build_absolute_uri(path)
        except DisallowedHost:
            logger.warning("feedback.unreviewed_url_disallowed_host")

    from apps.common.emailing.environment import get_email_base_url

    return f"{get_email_base_url()}{path}"


class FeedbackNotificationService:
    """Immediate staff notification path for new user-submitted feedback."""

    template_prefix = "feedback/email/new_feedback"

    def send_new_feedback_notification(
        self,
        feedback: UserFeedback,
        *,
        request: HttpRequest | None = None,
    ) -> int:
        body = feedback.body or ""
        preview = body[:FEEDBACK_BODY_PREVIEW_LENGTH]
        if len(body) > FEEDBACK_BODY_PREVIEW_LENGTH:
            preview = f"{preview}..."

        submitter = _feedback_actor_label(feedback.user)
        category = feedback.get_category_display()
        subject = f"[MedSim Feedback] {category} from {submitter}"
        context = {
            "feedback": feedback,
            "category_label": category,
            "submitted_by": submitter,
            "body_preview": preview,
            "detail_url": build_staff_feedback_detail_url(feedback, request=request),
            "unreviewed_url": build_staff_unreviewed_feedback_url(request=request),
            "platform_summary": self._platform_summary(feedback),
        }
        # TODO: Add a weekly summary digest path after the immediate workflow settles.
        return send_templated_email(
            to=[FEEDBACK_NOTIFICATION_RECIPIENT],
            subject=subject,
            template_prefix=self.template_prefix,
            context=context,
            request=request,
            from_email=FEEDBACK_NOTIFICATION_FROM_EMAIL,
        )

    def _platform_summary(self, feedback: UserFeedback) -> str:
        bits = [
            feedback.client_platform,
            feedback.client_version,
            feedback.os_version,
            feedback.device_model,
        ]
        return " / ".join(bit for bit in bits if bit) or "Unknown"


class FeedbackSubmissionService:
    """Create user feedback through explicit application orchestration."""

    def __init__(self, notification_service: FeedbackNotificationService | None = None):
        self.notification_service = notification_service or FeedbackNotificationService()

    def submit_feedback(self, *, request: HttpRequest, body) -> UserFeedback:
        from apps.accounts.context import resolve_request_account
        from apps.accounts.permissions import can_view_simulation

        user = request.auth

        if not body.body.strip():
            raise FeedbackSubmissionError(400, "Feedback body cannot be empty or whitespace only")

        if body.context is not None:
            try:
                context_size = len(json.dumps(body.context))
            except (TypeError, ValueError) as err:
                raise FeedbackSubmissionError(
                    400, "Context must be a JSON-serialisable object"
                ) from err
            if context_size > MAX_CONTEXT_BYTES:
                raise FeedbackSubmissionError(
                    400, "Context payload exceeds the maximum allowed size"
                )

        account = resolve_request_account(request, user=user)
        simulation = None
        if body.simulation_id is not None:
            from apps.simcore.models import Simulation

            try:
                simulation = Simulation.objects.select_related("account").get(pk=body.simulation_id)
            except Simulation.DoesNotExist as err:
                raise FeedbackSubmissionError(404, "Simulation not found") from err
            if not can_view_simulation(user, simulation):
                raise FeedbackSubmissionError(403, "You do not have access to this simulation")

        conversation = None
        if body.conversation_id is not None:
            from apps.simcore.models import Conversation

            try:
                conversation = Conversation.objects.select_related("simulation__account").get(
                    pk=body.conversation_id
                )
            except Conversation.DoesNotExist as err:
                raise FeedbackSubmissionError(404, "Conversation not found") from err

            if not can_view_simulation(user, conversation.simulation):
                raise FeedbackSubmissionError(
                    403,
                    "You do not have access to this conversation's simulation",
                )

            if simulation is not None and conversation.simulation_id != simulation.pk:
                raise FeedbackSubmissionError(
                    400,
                    "Conversation does not belong to the specified simulation",
                )

            if simulation is None:
                simulation = conversation.simulation

        metadata = _extract_request_metadata(request)
        valid_platforms = {v for v, _ in UserFeedback.ClientPlatform.choices}
        client_platform = (
            metadata["client_platform_raw"]
            if metadata["client_platform_raw"] in valid_platforms
            else UserFeedback.ClientPlatform.UNKNOWN
        )
        merged_context: dict = {**metadata["context_meta"], **(body.context or {})}

        with transaction.atomic():
            feedback = UserFeedback.objects.create(
                user=user,
                account=account,
                simulation=simulation,
                conversation=conversation,
                lab_type=_resolve_lab_type(simulation),
                category=body.category,
                source=UserFeedback.Source.IN_APP,
                status=UserFeedback.Status.NEW,
                title=(body.title or "").strip(),
                body=body.body.strip(),
                rating=body.rating,
                email=(getattr(user, "email", "") or "") if body.allow_follow_up else "",
                allow_follow_up=body.allow_follow_up,
                request_id=metadata["request_id"],
                client_platform=client_platform,
                client_version=metadata["client_version"],
                os_version=metadata["os_version"],
                device_model=metadata["device_model"],
                session_identifier=metadata["session_identifier"],
                context_json=merged_context,
            )
            FeedbackAuditEvent.objects.create(
                feedback=feedback,
                actor=user,
                event_type=FeedbackAuditEvent.EventType.CREATED,
                metadata_json={
                    "category": feedback.category,
                    "source": feedback.source,
                    "simulation_id": feedback.simulation_id,
                    "conversation_id": feedback.conversation_id,
                    "request_id": feedback.request_id,
                },
            )

        logger.info(
            "feedback.submitted",
            feedback_id=feedback.pk,
            user_id=user.pk,
            category=feedback.category,
            simulation_id=getattr(simulation, "pk", None),
        )
        self._send_notification(feedback, request=request)
        return feedback

    def _send_notification(self, feedback: UserFeedback, *, request: HttpRequest) -> None:
        try:
            sent_count = self.notification_service.send_new_feedback_notification(
                feedback,
                request=request,
            )
        except Exception as exc:
            logger.exception(
                "feedback.notification_email_failed",
                feedback_id=feedback.pk,
            )
            FeedbackAuditEvent.objects.create(
                feedback=feedback,
                actor=None,
                event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_FAILED,
                metadata_json={"error": str(exc)},
            )
            return

        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=None,
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT,
            metadata_json={
                "to": FEEDBACK_NOTIFICATION_RECIPIENT,
                "sent_count": sent_count,
            },
        )


class FeedbackWorkflowService:
    """Staff-facing feedback workflow mutations."""

    REVIEWED_STATUSES: ClassVar[set[str]] = {
        UserFeedback.Status.ACTION_REQUIRED,
        UserFeedback.Status.NO_ACTION_REQUIRED,
        UserFeedback.Status.PLANNED,
        UserFeedback.Status.RESOLVED,
        UserFeedback.Status.DUPLICATE,
        UserFeedback.Status.WONT_FIX,
    }

    BULK_ACTIONS: ClassVar[set[str]] = {
        "mark_reviewed",
        "mark_action_required",
        "mark_no_action_required",
        "mark_planned",
        "mark_resolved",
        "mark_duplicate",
        "mark_wont_fix",
        "archive",
    }

    BULK_STATUS_ACTIONS: ClassVar[dict[str, str]] = {
        "mark_action_required": UserFeedback.Status.ACTION_REQUIRED,
        "mark_no_action_required": UserFeedback.Status.NO_ACTION_REQUIRED,
        "mark_planned": UserFeedback.Status.PLANNED,
        "mark_resolved": UserFeedback.Status.RESOLVED,
        "mark_duplicate": UserFeedback.Status.DUPLICATE,
        "mark_wont_fix": UserFeedback.Status.WONT_FIX,
    }

    def mark_reviewed(self, feedback: UserFeedback, actor) -> UserFeedback:
        if feedback.is_reviewed:
            return feedback

        feedback.is_reviewed = True
        feedback.reviewed_at = timezone.now()
        feedback.reviewed_by = actor
        feedback.save(update_fields=["is_reviewed", "reviewed_at", "reviewed_by", "updated_at"])
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=actor,
            event_type=FeedbackAuditEvent.EventType.MARKED_REVIEWED,
            metadata_json={},
        )
        return feedback

    def set_status(self, feedback: UserFeedback, status: str, actor) -> UserFeedback:
        if status not in {v for v, _ in UserFeedback.Status.choices}:
            raise ValueError(f"Unsupported feedback status: {status}")

        old_status = feedback.status
        if old_status == status:
            if status in self.REVIEWED_STATUSES and not feedback.is_reviewed:
                self.mark_reviewed(feedback, actor)
            return feedback

        feedback.status = status
        feedback.save(update_fields=["status", "updated_at"])
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=actor,
            event_type=FeedbackAuditEvent.EventType.STATUS_CHANGED,
            metadata_json={"old_status": old_status, "new_status": status},
        )

        if status in self.REVIEWED_STATUSES and not feedback.is_reviewed:
            feedback.refresh_from_db()
            self.mark_reviewed(feedback, actor)
        return feedback

    def archive(self, feedback: UserFeedback, actor) -> UserFeedback:
        if feedback.is_archived:
            return feedback

        feedback.is_archived = True
        feedback.archived_at = timezone.now()
        feedback.archived_by = actor
        feedback.save(update_fields=["is_archived", "archived_at", "archived_by", "updated_at"])
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=actor,
            event_type=FeedbackAuditEvent.EventType.ARCHIVED,
            metadata_json={},
        )
        return feedback

    def unarchive(self, feedback: UserFeedback, actor) -> UserFeedback:
        if not feedback.is_archived:
            return feedback

        feedback.is_archived = False
        feedback.archived_at = None
        feedback.archived_by = None
        feedback.save(update_fields=["is_archived", "archived_at", "archived_by", "updated_at"])
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=actor,
            event_type=FeedbackAuditEvent.EventType.UNARCHIVED,
            metadata_json={},
        )
        return feedback

    def add_remark(self, feedback: UserFeedback, actor, body: str) -> FeedbackRemark:
        remark_body = body.strip()
        if not remark_body:
            raise ValueError("Remark body cannot be empty")

        with transaction.atomic():
            remark = FeedbackRemark.objects.create(
                feedback=feedback,
                author=actor,
                body=remark_body,
            )
            FeedbackAuditEvent.objects.create(
                feedback=feedback,
                actor=actor,
                event_type=FeedbackAuditEvent.EventType.REMARK_ADDED,
                metadata_json={"remark_id": remark.pk},
            )
        return remark

    def bulk_update(
        self,
        feedback_items: Iterable[UserFeedback],
        actor,
        action: str,
    ) -> int:
        if action not in self.BULK_ACTIONS:
            raise ValueError(f"Unsupported bulk action: {action}")

        items = list(feedback_items)
        affected_ids = [item.pk for item in items]
        with transaction.atomic():
            for feedback in items:
                if action == "mark_reviewed":
                    self.mark_reviewed(feedback, actor)
                elif action == "archive":
                    self.archive(feedback, actor)
                else:
                    self.set_status(feedback, self.BULK_STATUS_ACTIONS[action], actor)

            for feedback in items:
                FeedbackAuditEvent.objects.create(
                    feedback=feedback,
                    actor=actor,
                    event_type=FeedbackAuditEvent.EventType.BULK_UPDATED,
                    metadata_json={
                        "action": action,
                        "affected_ids": affected_ids,
                        "affected_count": len(affected_ids),
                    },
                )
        return len(affected_ids)


class FeedbackQueryService:
    """Read-side helpers for staff feedback inboxes, badges, and metrics.

    "Open" is a reporting concept: unarchived feedback that is not resolved,
    duplicate, or won't-fix.
    """

    OPEN_EXCLUDED_STATUSES: ClassVar[set[str]] = {
        UserFeedback.Status.RESOLVED,
        UserFeedback.Status.DUPLICATE,
        UserFeedback.Status.WONT_FIX,
    }

    def staff_inbox_queryset(self, params):
        qs = UserFeedback.objects.select_related(
            "user",
            "simulation",
            "reviewed_by",
            "archived_by",
        )

        archived = (params.get("archived") or "").strip()
        if archived == "archived":
            qs = qs.filter(is_archived=True)
        elif archived == "all":
            pass
        else:
            qs = qs.filter(is_archived=False)

        reviewed = (params.get("reviewed") or "").strip()
        if reviewed == "reviewed":
            qs = qs.filter(is_reviewed=True)
        elif reviewed == "unreviewed":
            qs = qs.filter(is_reviewed=False)

        category = (params.get("category") or "").strip()
        if category:
            qs = qs.filter(category=category)

        status = (params.get("status") or "").strip()
        if status:
            qs = qs.filter(status=status)

        platform = (params.get("platform") or params.get("client_platform") or "").strip()
        if platform:
            qs = qs.filter(client_platform=platform)

        user_query = (params.get("user") or "").strip()
        if user_query:
            if user_query.isdigit():
                qs = qs.filter(user_id=int(user_query))
            else:
                qs = qs.filter(
                    Q(user__email__icontains=user_query)
                    | Q(user__first_name__icontains=user_query)
                    | Q(user__last_name__icontains=user_query)
                )

        simulation_query = (params.get("simulation") or "").strip()
        if simulation_query:
            if simulation_query.isdigit():
                qs = qs.filter(simulation_id=int(simulation_query))
            else:
                qs = qs.none()

        date_from = parse_date((params.get("date_from") or "").strip())
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = parse_date((params.get("date_to") or "").strip())
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        search = (params.get("q") or "").strip()
        if search:
            search_filter = (
                Q(title__icontains=search)
                | Q(body__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
            )
            if search.isdigit():
                search_filter |= Q(simulation_id=int(search))
            qs = qs.filter(search_filter)

        return qs.order_by("is_reviewed", "-created_at", "-id")

    def analytics(self) -> dict[str, int]:
        now = timezone.now()
        recent_cutoff = now - timedelta(days=30)
        base = UserFeedback.objects.all()
        return {
            "open": base.filter(is_archived=False)
            .exclude(status__in=self.OPEN_EXCLUDED_STATUSES)
            .count(),
            "planned": base.filter(is_archived=False, status=UserFeedback.Status.PLANNED).count(),
            "resolved_last_30_days": base.filter(
                status=UserFeedback.Status.RESOLVED,
                reviewed_at__gte=recent_cutoff,
            ).count(),
            "duplicate": base.filter(
                is_archived=False, status=UserFeedback.Status.DUPLICATE
            ).count(),
            "wont_fix": base.filter(is_archived=False, status=UserFeedback.Status.WONT_FIX).count(),
            "unreviewed": self.unreviewed_count(),
        }

    def unreviewed_count(self) -> int:
        return UserFeedback.objects.filter(is_reviewed=False, is_archived=False).count()
