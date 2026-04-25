"""Tests for staging-environment invite email instructions.

Covers:
  - invitation.html / invitation.txt: staging block present in staging, absent in production
  - staging_account_ready.html / staging_account_ready.txt: template content
  - send_staging_account_ready_email_task: sends in staging, skips in production, idempotent
  - maybe_send_staging_account_ready_email: enqueues only in staging, respects idempotency guard
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.utils import timezone
import pytest

from apps.accounts.models import Invitation, UserRole
from apps.accounts.services.invitations import maybe_send_staging_account_ready_email
from apps.accounts.tasks import send_staging_account_ready_email_task

pytestmark = pytest.mark.django_db

User = get_user_model()

_INVITE_CTX_BASE = {
    "accept_url": "https://medsim-staging.jackfruitco.com/accept/TOKEN/",
    "inviter_name": "Dr. Test",
    "inviter_email": "drtest@example.com",
    "product_access_bundle": "",
    "support_email": "support@jackfruitco.com",
    "email_base_url": "https://medsim-staging.jackfruitco.com",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def role():
    return UserRole.objects.create(title="Staging Email Test Role")


@pytest.fixture
def staff_user(role):
    return User.objects.create_user(
        email="staff-staging@example.com",
        password="password",
        role=role,
        is_staff=True,
    )


@pytest.fixture
def claimed_invitation(staff_user):
    inv = Invitation.objects.create(
        email="invitee-staging@example.com",
        invited_by=staff_user,
    )
    inv.is_claimed = True
    inv.claimed_at = timezone.now()
    inv.save(update_fields=["is_claimed", "claimed_at"])
    return inv


@pytest.fixture
def unclaimed_invitation(staff_user):
    return Invitation.objects.create(
        email="invitee-unclaimed@example.com",
        invited_by=staff_user,
    )


# ---------------------------------------------------------------------------
# Invite email template: staging block present / absent
# ---------------------------------------------------------------------------


def _invitation_stub():
    inv = Invitation.__new__(Invitation)
    inv.expires_at = timezone.now() + timedelta(days=3)
    return inv


def test_invite_html_staging_block_present_in_staging():
    html = render_to_string(
        "accounts/emails/invitation.html",
        {**_INVITE_CTX_BASE, "is_staging": True, "invitation": _invitation_stub()},
    )
    assert "This is a staging account" in html
    assert "switch the app environment to Staging" in html
    assert "If you stay on Production" in html


def test_invite_html_staging_block_absent_in_production():
    html = render_to_string(
        "accounts/emails/invitation.html",
        {**_INVITE_CTX_BASE, "is_staging": False, "invitation": _invitation_stub()},
    )
    assert "This is a staging account" not in html
    assert "If you stay on Production" not in html


def test_invite_txt_staging_block_present_in_staging():
    txt = render_to_string(
        "accounts/emails/invitation.txt",
        {**_INVITE_CTX_BASE, "is_staging": True, "invitation": _invitation_stub()},
    )
    assert "This is a staging account" in txt
    assert "If you stay on Production" in txt


def test_invite_txt_staging_block_absent_in_production():
    txt = render_to_string(
        "accounts/emails/invitation.txt",
        {**_INVITE_CTX_BASE, "is_staging": False, "invitation": _invitation_stub()},
    )
    assert "This is a staging account" not in txt
    assert "If you stay on Production" not in txt


# ---------------------------------------------------------------------------
# staging_account_ready templates: content checks
# ---------------------------------------------------------------------------


def test_staging_account_ready_html_contains_ios_instructions():
    html = render_to_string(
        "accounts/emails/staging_account_ready.html",
        {**_INVITE_CTX_BASE, "is_staging": True},
    )
    assert "Staging" in html
    assert "If the app is set to Production" in html
    assert "Settings" in html
    assert "Environment" in html


def test_staging_account_ready_txt_contains_ios_instructions():
    txt = render_to_string(
        "accounts/emails/staging_account_ready.txt",
        {**_INVITE_CTX_BASE, "is_staging": True},
    )
    assert "Staging" in txt
    assert "If the app is set to Production" in txt
    assert "Settings" in txt
    assert "Environment" in txt


# ---------------------------------------------------------------------------
# send_staging_account_ready_email_task
# ---------------------------------------------------------------------------


@patch("apps.accounts.tasks.send_templated_email", return_value=1)
def test_task_sends_in_staging(mock_send, claimed_invitation):
    send_staging_account_ready_email_task(claimed_invitation.pk, environment_hint="staging")

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["to"] == ["invitee-staging@example.com"]
    assert "staging_account_ready" in call_kwargs["template_prefix"]
    assert call_kwargs["environment_hint"] == "staging"

    claimed_invitation.refresh_from_db()
    assert claimed_invitation.staging_setup_reminder_sent_at is not None


@patch("apps.accounts.tasks.send_templated_email", return_value=1)
def test_task_skips_in_production(mock_send, claimed_invitation):
    send_staging_account_ready_email_task(claimed_invitation.pk, environment_hint="production")

    mock_send.assert_not_called()
    claimed_invitation.refresh_from_db()
    assert claimed_invitation.staging_setup_reminder_sent_at is None


@patch("apps.accounts.tasks.send_templated_email", return_value=1)
def test_task_not_sent_twice(mock_send, claimed_invitation):
    send_staging_account_ready_email_task(claimed_invitation.pk, environment_hint="staging")
    assert mock_send.call_count == 1

    send_staging_account_ready_email_task(claimed_invitation.pk, environment_hint="staging")
    assert mock_send.call_count == 1  # idempotent — second call is a no-op


@patch("apps.accounts.tasks.send_templated_email", return_value=1)
def test_task_skips_unclaimed_invitation(mock_send, unclaimed_invitation):
    send_staging_account_ready_email_task(unclaimed_invitation.pk, environment_hint="staging")

    mock_send.assert_not_called()


@patch("apps.accounts.tasks.send_templated_email", return_value=1)
def test_task_skips_nonexistent_invitation(mock_send):
    send_staging_account_ready_email_task(999999, environment_hint="staging")

    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# maybe_send_staging_account_ready_email service
# ---------------------------------------------------------------------------


@patch("apps.accounts.tasks.send_staging_account_ready_email_task.delay")
def test_service_enqueues_in_staging(
    mock_delay, unclaimed_invitation, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        maybe_send_staging_account_ready_email(
            invitation=unclaimed_invitation, environment_hint="staging"
        )

    mock_delay.assert_called_once_with(unclaimed_invitation.id, "staging")


@patch("apps.accounts.tasks.send_staging_account_ready_email_task.delay")
def test_service_does_not_enqueue_in_production(
    mock_delay, unclaimed_invitation, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        maybe_send_staging_account_ready_email(
            invitation=unclaimed_invitation, environment_hint="production"
        )

    mock_delay.assert_not_called()


@patch("apps.accounts.tasks.send_staging_account_ready_email_task.delay")
def test_service_does_not_enqueue_when_already_sent(
    mock_delay, unclaimed_invitation, django_capture_on_commit_callbacks
):
    unclaimed_invitation.staging_setup_reminder_sent_at = timezone.now()
    unclaimed_invitation.save(update_fields=["staging_setup_reminder_sent_at"])

    with django_capture_on_commit_callbacks(execute=True):
        maybe_send_staging_account_ready_email(
            invitation=unclaimed_invitation, environment_hint="staging"
        )

    mock_delay.assert_not_called()


@patch("apps.accounts.tasks.send_staging_account_ready_email_task.delay")
def test_service_does_not_enqueue_for_invitation_without_email(
    mock_delay, staff_user, django_capture_on_commit_callbacks
):
    inv = Invitation.objects.create(invited_by=staff_user)  # no email

    with django_capture_on_commit_callbacks(execute=True):
        maybe_send_staging_account_ready_email(invitation=inv, environment_hint="staging")

    mock_delay.assert_not_called()
