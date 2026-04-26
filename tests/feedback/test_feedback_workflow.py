from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.test import Client, RequestFactory
from django.utils import timezone
import pytest

from api.v1.schemas.feedback import FeedbackCreate
from apps.feedback.models import FeedbackAuditEvent, FeedbackRemark, UserFeedback
from apps.feedback.services import (
    FeedbackQueryService,
    FeedbackSubmissionService,
    FeedbackWorkflowService,
)
from apps.feedback.tasks import send_new_feedback_notification_task


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
    def test_submit_feedback_creates_defaults_audit_and_enqueues_email(
        self, user, monkeypatch, django_capture_on_commit_callbacks
    ):
        enqueued = []

        def fake_delay(feedback_id, request_meta=None):
            enqueued.append((feedback_id, request_meta))

        monkeypatch.setattr(
            "apps.feedback.tasks.send_new_feedback_notification_task.delay",
            fake_delay,
        )
        body = FeedbackCreate(
            category="bug_report",
            title="Crash",
            body="App crashed after tapping start.",
            context={"screen": "home"},
        )

        with django_capture_on_commit_callbacks(execute=True) as callbacks:
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
        assert not feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT
        ).exists()
        assert len(callbacks) == 1
        assert enqueued == [(feedback.pk, {"request_id": "corr-123"})]
        assert len(mail.outbox) == 0

    def test_notification_enqueue_failure_does_not_fail_submission(
        self, user, monkeypatch, django_capture_on_commit_callbacks
    ):
        def failing_delay(feedback_id, request_meta=None):
            raise RuntimeError("broker down")

        monkeypatch.setattr(
            "apps.feedback.tasks.send_new_feedback_notification_task.delay",
            failing_delay,
        )
        body = FeedbackCreate(category="other", body="Still save this")
        with django_capture_on_commit_callbacks(execute=True):
            feedback = FeedbackSubmissionService().submit_feedback(
                request=_request_for(user),
                body=body,
            )

        assert feedback.pk
        assert feedback.audit_events.filter(
            event_type=FeedbackAuditEvent.EventType.CREATED
        ).exists()
        assert not feedback.audit_events.exclude(
            event_type=FeedbackAuditEvent.EventType.CREATED
        ).exists()


@pytest.mark.django_db
class TestFeedbackNotificationTask:
    def test_success_sends_email_and_creates_audit(self, user):
        body = "A" * 450
        feedback = UserFeedback.objects.create(
            user=user,
            category=UserFeedback.Category.BUG_REPORT,
            title="Crash",
            body=body,
            client_platform=UserFeedback.ClientPlatform.IOS,
            client_version="2.4.1",
        )

        send_new_feedback_notification_task.run(
            feedback.pk,
            request_meta={"request_id": "corr-123"},
        )

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["feedback@jackfruitco.com"]
        assert message.from_email == "noreply@jackfruitco.com"
        assert "[MedSim Feedback] Bug Report" in message.subject
        assert f"/staff/feedback/{feedback.pk}/" in message.body
        assert "A" * 400 in message.body
        assert "A" * 401 not in message.body
        audit = feedback.audit_events.get(
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT
        )
        assert audit.metadata_json["to"] == "feedback@jackfruitco.com"
        assert audit.metadata_json["sent_count"] == 1
        assert audit.metadata_json["request_meta"]["request_id"] == "corr-123"

    def test_failure_records_audit_event(self, user, monkeypatch):
        feedback = UserFeedback.objects.create(
            user=user,
            category=UserFeedback.Category.OTHER,
            body="Send failure",
        )

        def fail_send(self, feedback):
            raise RuntimeError("smtp down")

        monkeypatch.setattr(
            "apps.feedback.tasks.FeedbackNotificationService.send_new_feedback_notification",
            fail_send,
        )

        send_new_feedback_notification_task.run(feedback.pk)

        assert len(mail.outbox) == 0
        audit = feedback.audit_events.get(
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_FAILED
        )
        assert "smtp down" in audit.metadata_json["error"]

    def test_missing_feedback_exits_safely(self):
        send_new_feedback_notification_task.run(999999)

        assert len(mail.outbox) == 0

    def test_existing_success_audit_skips_duplicate_send(self, user, monkeypatch):
        feedback = UserFeedback.objects.create(
            user=user,
            category=UserFeedback.Category.OTHER,
            body="Already sent",
        )
        FeedbackAuditEvent.objects.create(
            feedback=feedback,
            actor=None,
            event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT,
            metadata_json={},
        )
        called = False

        def fail_if_called(self, feedback):
            nonlocal called
            called = True
            raise AssertionError("notification should not be sent twice")

        monkeypatch.setattr(
            "apps.feedback.tasks.FeedbackNotificationService.send_new_feedback_notification",
            fail_if_called,
        )

        send_new_feedback_notification_task.run(feedback.pk)

        assert called is False
        assert len(mail.outbox) == 0
        assert (
            feedback.audit_events.filter(
                event_type=FeedbackAuditEvent.EventType.NOTIFICATION_EMAIL_SENT
            ).count()
            == 1
        )


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

    def test_resolved_status_sets_and_clears_resolved_at(self, user, staff_user):
        feedback = UserFeedback.objects.create(user=user, category="other", body="Resolve me")
        service = FeedbackWorkflowService()

        service.set_status(feedback, UserFeedback.Status.RESOLVED, staff_user)
        feedback.refresh_from_db()
        assert feedback.resolved_at is not None

        service.set_status(feedback, UserFeedback.Status.PLANNED, staff_user)
        feedback.refresh_from_db()
        assert feedback.resolved_at is None

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
class TestFeedbackAnalytics:
    def test_resolved_last_30_days_uses_resolved_at_not_reviewed_at(self, user, staff_user):
        now = timezone.now()
        UserFeedback.objects.create(
            user=user,
            category="other",
            body="Old resolution",
            status=UserFeedback.Status.RESOLVED,
            is_reviewed=True,
            reviewed_at=now,
            reviewed_by=staff_user,
            resolved_at=now - timedelta(days=45),
        )
        UserFeedback.objects.create(
            user=user,
            category="other",
            body="Recent resolution",
            status=UserFeedback.Status.RESOLVED,
            is_reviewed=True,
            reviewed_at=now - timedelta(days=45),
            reviewed_by=staff_user,
            resolved_at=now,
        )

        analytics = FeedbackQueryService().analytics()

        assert analytics["resolved_last_30_days"] == 1


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
        assert b'id="staff-feedback-banner"' in response.content

    def test_staff_banner_hidden_without_unreviewed_count(self, user, staff_user):
        UserFeedback.objects.create(
            user=user,
            category="other",
            body="Reviewed",
            is_reviewed=True,
        )
        client = Client()
        client.force_login(staff_user)

        response = client.get("/staff/feedback/")

        assert response.status_code == 200
        assert b'id="staff-feedback-banner"' not in response.content

    def test_non_staff_never_sees_staff_banner(self, user):
        UserFeedback.objects.create(
            user=user,
            category="other",
            body="Unreviewed",
            is_reviewed=False,
        )
        client = Client()
        client.force_login(user)

        response = client.get("/")

        assert b'id="staff-feedback-banner"' not in response.content

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

    def test_default_bulk_action_does_not_mutate_archived_feedback(self, user, staff_user):
        archived = UserFeedback.objects.create(
            user=user,
            category="other",
            body="Archived bulk",
            is_archived=True,
            status=UserFeedback.Status.NEW,
        )
        client = Client()
        client.force_login(staff_user)

        response = client.post(
            "/staff/feedback/",
            {"action": "mark_resolved", "feedback_ids": [str(archived.pk)]},
        )

        assert response.status_code == 302
        archived.refresh_from_db()
        assert archived.status == UserFeedback.Status.NEW
        assert archived.is_reviewed is False

    def test_archived_filter_bulk_action_can_mutate_archived_feedback(self, user, staff_user):
        archived = UserFeedback.objects.create(
            user=user,
            category="other",
            body="Archived bulk",
            is_archived=True,
            status=UserFeedback.Status.NEW,
        )
        client = Client()
        client.force_login(staff_user)

        response = client.post(
            "/staff/feedback/?archived=archived",
            {"action": "mark_resolved", "feedback_ids": [str(archived.pk)]},
        )

        assert response.status_code == 302
        archived.refresh_from_db()
        assert archived.status == UserFeedback.Status.RESOLVED
        assert archived.is_reviewed is True
        assert archived.resolved_at is not None
