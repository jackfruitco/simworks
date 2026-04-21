from __future__ import annotations

from celery import shared_task

from config.logging import get_logger

from .models import FeedbackAuditEvent, UserFeedback
from .services import FEEDBACK_NOTIFICATION_RECIPIENT, FeedbackNotificationService

logger = get_logger(__name__)


@shared_task(bind=True, ignore_result=True)
def send_new_feedback_notification_task(
    self,
    feedback_id: int,
    request_meta: dict | None = None,
) -> None:
    """Send the staff notification email for a newly submitted feedback row."""
    try:
        feedback = UserFeedback.objects.select_related("user", "simulation", "conversation").get(
            pk=feedback_id
        )
    except UserFeedback.DoesNotExist:
        logger.warning(
            "feedback.notification_feedback_missing",
            feedback_id=feedback_id,
        )
        return

    if feedback.audit_events.filter(
        event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT
    ).exists():
        logger.info(
            "feedback.notification_email_already_sent",
            feedback_id=feedback_id,
        )
        return

    audit_metadata = {"request_meta": request_meta or {}}
    try:
        sent_count = FeedbackNotificationService().send_new_feedback_notification(feedback)
    except Exception as exc:
        logger.exception(
            "feedback.notification_email_failed",
            feedback_id=feedback_id,
        )
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=None,
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_FAILED,
            metadata_json={
                **audit_metadata,
                "error": str(exc),
            },
        )
        return

    FeedbackAuditEvent.objects.create(
        feedback=feedback,
        actor=None,
        event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT,
        metadata_json={
            **audit_metadata,
            "to": FEEDBACK_NOTIFICATION_RECIPIENT,
            "sent_count": sent_count,
        },
    )
    logger.info(
        "feedback.notification_email_sent",
        feedback_id=feedback_id,
        sent_count=sent_count,
    )
