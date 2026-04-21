from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.test import Client, RequestFactory
from django.utils import timezone
import pytest

from api.v1.schemas.feedback import FeedbackCreate
from apps.feedback.models import FeedbackAuditEvent, FeedbackRemark, UserFeedback
from apps.feedback.services import FeedbackSubmissionService, FeedbackWorkflowService


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Feedback Workflow Tester")


@pytest.fixture
def user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="feedback_workflow@example.com",
        first_name="Feedback",
        last_name="User",
        role=user_role,
    )


@pytest.fixture
def staff_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        password="testpass123",
        email="staff_workflow@example.com",
        role=user_role,
        is_staff=True,
    )


def _request_for(user):
    request = RequestFactory().post(
        "/api/v1/feedback/",
        HTTP_HOST="testserver",
        HTTP_X_PLATFORM="ios",
        HTTP_X_APP_VERSION="2.4.1",
        HTTP_X_OS_VERSION="18.1",
        HTTP_X_DEVICE_MODEL="iPhone16,1",
        HTTP_X_SESSION_ID="session-123",
    )
    request.user = user
    request.auth = user
    request.correlation_id = "corr-123"
    return request


@pytest.mark.django_db
class TestFeedbackSubmissionService:
    def test_submit_feedback_creates_defaults_audit_and_email(self, user):
        body = FeedbackCreate(
            category="bug_report",
            title="Crash",
            body="App crashed after tapping start.",
            context={"screen": "home"},
        )

        feedback = FeedbackSubmissionService().submit_feedback(
            request=_request_for(user),
            body=body,
        )

        assert feedback.status == UserFeedback.Status.NEW
        assert feedback.is_reviewed is False
        assert feedback.is_archived is False
        assert feedback.email == user.email
        assert feedback.client_platform == "ios"
        assert feedback.context_json["screen"] == "home"
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.CREATED
        ).exists()
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT
        ).exists()
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["feedback@jackfruitco.com"]
        assert message.from_email == "noreply@jackfruitco.com"
        assert "[MedSim Feedback] Bug Report" in message.subject
        assert f"/staff/feedback/{feedback.pk}/" in message.body

    def test_notification_failure_does_not_fail_submission(self, user):
        class FailingNotificationService:
            def send_new_feedback_notification(self, feedback, *, request=None):
                raise RuntimeError("smtp down")

        body = FeedbackCreate(category="other", body="Still save this")
        feedback = FeedbackSubmissionService(
            notification_service=FailingNotificationService()
        ).submit_feedback(
            request=_request_for(user),
            body=body,
        )

        assert feedback.pk
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_FAILED
        ).exists()


@pytest.mark.django_db
class TestFeedbackWorkflowService:
    def test_mark_reviewed_sets_fields_and_audit(self, user, staff_user):
        feedback = UserFeedback.objects.create(user=user, category="other", body="Review me")

        FeedbackWorkflowService().mark_reviewed(feedback, staff_user)
        feedback.refresh_from_db()

        assert feedback.is_reviewed is True
        assert feedback.reviewed_by == staff_user
        assert feedback.reviewed_at is not None
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.MARKED_REVIEWED
        ).exists()

    @pytest.mark.parametrize(
        "status",
        [
            UserFeedback.Status.ACTION_REQUIRED,
            UserFeedback.Status.NO_ACTION_REQUIRED,
            UserFeedback.Status.PLANNED,
            UserFeedback.Status.RESOLVED,
            UserFeedback.Status.DUPLICATE,
            UserFeedback.Status.WONT_FIX,
        ],
    )
    def test_set_status_auto_reviews(self, user, staff_user, status):
        feedback = UserFeedback.objects.create(user=user, category="other", body="Set status")

        FeedbackWorkflowService().set_status(feedback, status, staff_user)
        feedback.refresh_from_db()

        assert feedback.status == status
        assert feedback.is_reviewed is True
        assert feedback.reviewed_by == staff_user
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.STATUS_CHANGED
        ).exists()

    def test_archive_unarchive_and_remark_create_audit(self, user, staff_user):
        feedback = UserFeedback.objects.create(user=user, category="other", body="Archive me")
        service = FeedbackWorkflowService()

        service.archive(feedback, staff_user)
        feedback.refresh_from_db()
        assert feedback.is_archived is True
        assert feedback.archived_by == staff_user

        service.unarchive(feedback, staff_user)
        feedback.refresh_from_db()
        assert feedback.is_archived is False

        remark = service.add_remark(feedback, staff_user, "Developer note")
        assert remark.body == "Developer note"
        assert FeedbackRemark.objects.filter(feedback=feedback).count() == 1
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.REMARK_ADDED
        ).exists()
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.ARCHIVED
        ).exists()
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.UNARCHIVED
        ).exists()

    def test_bulk_update_creates_bulk_audit(self, user, staff_user):
        items = [
            UserFeedback.objects.create(user=user, category="other", body=f"Bulk {idx}")
            for idx in range(2)
        ]

        count = FeedbackWorkflowService().bulk_update(
            UserFeedback.objects.filter(pk__in=[item.pk for item in items]),
            staff_user,
            "mark_resolved",
        )

        assert count == 2
        assert UserFeedback.objects.filter(status=UserFeedback.Status.RESOLVED).count() == 2
        assert (
            FeedbackAuditEvent.objects.filter(
                event_type=FeedbackAuditEvent.EventType.BULK_UPDATED
            ).count()
            == 2
        )


@pytest.mark.django_db
class TestFeedbackStaffWeb:
    def test_inbox_requires_staff(self, user):
        client = Client()
        client.force_login(user)

        response = client.get("/staff/feedback/")

        assert response.status_code != 200

    def test_default_inbox_excludes_archived_and_orders_unreviewed_first(self, user, staff_user):
        reviewed = UserFeedback.objects.create(
            user=user,
            category="other",
            body="Reviewed newest",
            is_reviewed=True,
        )
        unreviewed = UserFeedback.objects.create(
            user=user,
            category="other",
            body="Unreviewed older",
            is_reviewed=False,
        )
        archived = UserFeedback.objects.create(
            user=user,
            category="other",
            body="Archived",
            is_reviewed=False,
            is_archived=True,
        )
        UserFeedback.objects.filter(pk=reviewed.pk).update(created_at=timezone.now())
        UserFeedback.objects.filter(pk=unreviewed.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )

        client = Client()
        client.force_login(staff_user)
        response = client.get("/staff/feedback/")

        assert response.status_code == 200
        items = list(response.context["feedback_items"])
        assert items[0].pk == unreviewed.pk
        assert reviewed in items
        assert archived not in items
        assert response.context["unreviewed_feedback_count"] == 1

    def test_detail_actions_and_sections(self, user, staff_user):
        feedback = UserFeedback.objects.create(user=user, category="bug_report", body="Broken")
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=staff_user,
            event_type=FeedbackAuditEvent.EventType.CREATED,
            metadata_json={},
        )
        FeedbackRemark.objects.create(feedback=feedback, author=staff_user, body="Investigating")

        client = Client()
        client.force_login(staff_user)
        response = client.get(f"/staff/feedback/{feedback.pk}/")

        assert response.status_code == 200
        assert b"Developer Team Remarks" in response.content
        assert b"Audit History" in response.content
        assert b"Investigating" in response.content

        response = client.post(f"/staff/feedback/{feedback.pk}/mark-reviewed/")
        assert response.status_code == 302
        feedback.refresh_from_db()
        assert feedback.is_reviewed is True

        response = client.post(
            f"/staff/feedback/{feedback.pk}/set-status/",
            {"status": UserFeedback.Status.RESOLVED},
        )
        assert response.status_code == 302
        feedback.refresh_from_db()
        assert feedback.status == UserFeedback.Status.RESOLVED

        response = client.post(
            f"/staff/feedback/{feedback.pk}/remarks/",
            {"body": "Second remark"},
        )
        assert response.status_code == 302
        assert feedback.remarks.filter(body="Second remark").exists()

        response = client.post(f"/staff/feedback/{feedback.pk}/archive/")
        assert response.status_code == 302
        feedback.refresh_from_db()
        assert feedback.is_archived is True

    def test_bulk_action_from_inbox(self, user, staff_user):
        feedback = UserFeedback.objects.create(user=user, category="other", body="Bulk")
        client = Client()
        client.force_login(staff_user)

        response = client.post(
            "/staff/feedback/",
            {"action": "mark_action_required", "feedback_ids": [str(feedback.pk)]},
        )

        assert response.status_code == 302
        feedback.refresh_from_db()
        assert feedback.status == UserFeedback.Status.ACTION_REQUIRED
        assert feedback.is_reviewed is True
