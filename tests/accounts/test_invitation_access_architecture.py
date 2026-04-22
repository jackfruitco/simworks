from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
import pytest

from apps.accounts.models import (
    AccountAuditEvent,
    AccountMembership,
    Invitation,
    InvitationAuditEvent,
    UserRole,
)
from apps.accounts.services import get_personal_account_for_user
from apps.accounts.services.invitations import (
    InvitationEmailMismatchError,
    InvitationNotClaimableError,
    claim_invitation_for_user,
    create_invitation,
    resend_invitation,
    revoke_invitation,
)
from apps.accounts.tasks import send_invitation_email_task
from apps.billing.catalog import ProductCode
from apps.billing.models import Entitlement

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def role():
    return UserRole.objects.create(title="Invitation Test Role")


@pytest.fixture
def staff_user(role):
    return User.objects.create_user(
        email="staff@example.com",
        password="password",
        role=role,
        is_staff=True,
    )


@pytest.fixture
def superuser(role):
    return User.objects.create_user(
        email="super@example.com",
        password="password",
        role=role,
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def regular_user(role):
    return User.objects.create_user(
        email="regular@example.com",
        password="password",
        role=role,
    )


@pytest.fixture
def capture_invitation_email(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "apps.accounts.tasks.send_invitation_email_task.delay",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    return calls


def test_staff_create_invitation_queues_email_without_membership_or_entitlement(
    staff_user,
    capture_invitation_email,
    django_capture_on_commit_callbacks,
):
    with django_capture_on_commit_callbacks(execute=True):
        invitation = create_invitation(
            invited_by=staff_user,
            email=" Invitee@Example.com ",
        )

    assert invitation.email == "invitee@example.com"
    assert invitation.product_code == ""
    assert invitation.membership_role == AccountMembership.Role.GENERAL_USER
    assert AccountMembership.objects.filter(invite_email="invitee@example.com").count() == 0
    assert Entitlement.objects.count() == 0
    assert capture_invitation_email[0][0] == (invitation.id, None)
    assert InvitationAuditEvent.objects.filter(
        invitation=invitation,
        event_type="invitation.created",
    ).exists()


def test_non_staff_cannot_create_invitation(regular_user):
    with pytest.raises(PermissionDenied):
        create_invitation(invited_by=regular_user, email="invitee@example.com")


def test_only_superusers_can_attach_product_access_bundle(
    staff_user, superuser, capture_invitation_email
):
    with pytest.raises(PermissionDenied):
        create_invitation(
            invited_by=staff_user,
            email="plain@example.com",
            product_code=ProductCode.CHATLAB_GO.value,
        )

    invitation = create_invitation(
        invited_by=superuser,
        email="bundle@example.com",
        product_code=ProductCode.CHATLAB_GO.value,
    )

    assert invitation.product_access_bundle_display_name == "ChatLab Go"


def test_resend_rotates_token_extends_expiry_and_queues_email(
    staff_user,
    capture_invitation_email,
    django_capture_on_commit_callbacks,
):
    invitation = create_invitation(invited_by=staff_user, email="resend@example.com")
    old_token = invitation.token
    Invitation.objects.filter(pk=invitation.pk).update(
        expires_at=timezone.now() + timedelta(hours=1)
    )
    invitation.refresh_from_db()
    old_expiry = invitation.expires_at

    with django_capture_on_commit_callbacks(execute=True):
        resent = resend_invitation(invitation=invitation, resent_by=staff_user)

    assert resent.token != old_token
    assert resent.expires_at > old_expiry
    assert capture_invitation_email[-1][0] == (resent.id, None)
    assert InvitationAuditEvent.objects.filter(
        invitation=resent,
        event_type="invitation.resent",
    ).exists()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_invitation_email_task_marks_sent_on_success(staff_user):
    invitation = Invitation.objects.create(
        invited_by=staff_user,
        email="mail@example.com",
        product_code=ProductCode.CHATLAB_GO.value,
    )

    send_invitation_email_task.run(invitation.id, "production")

    invitation.refresh_from_db()
    assert invitation.sent_at is not None
    assert invitation.last_sent_at is not None
    assert invitation.send_count == 1
    assert len(mail.outbox) == 1
    assert "Product Access Bundle: ChatLab Go" in mail.outbox[0].body
    assert InvitationAuditEvent.objects.filter(
        invitation=invitation,
        event_type="invitation.sent",
    ).exists()


def test_claim_invitation_repairs_existing_membership_and_stable_entitlement_source_ref(
    superuser,
    role,
):
    invitation = Invitation.objects.create(
        invited_by=superuser,
        email="claim@example.com",
        product_code=ProductCode.TRAINERLAB_GO.value,
    )
    user = User.objects.create_user(
        email="claim@example.com",
        password="password",
        role=role,
    )

    account, membership, entitlement = claim_invitation_for_user(
        invitation=invitation,
        user=user,
    )

    invitation.refresh_from_db()
    assert invitation.is_claimed is True
    assert invitation.claimed_by == user
    assert invitation.claimed_account == account
    assert account == get_personal_account_for_user(user)
    assert membership.account == account
    assert membership.user == user
    assert membership.role == AccountMembership.Role.ORG_ADMIN
    assert membership.status == AccountMembership.Status.ACTIVE
    assert membership.ended_at is None
    assert entitlement is not None
    assert (
        entitlement.source_ref == f"invitation:{invitation.uuid}:{ProductCode.TRAINERLAB_GO.value}"
    )
    assert entitlement.scope_type == Entitlement.ScopeType.USER
    assert AccountAuditEvent.objects.filter(
        account=account,
        event_type="entitlement.granted_from_invitation",
    ).exists()


def test_claim_invitation_without_product_code_grants_no_entitlement(staff_user, role):
    invitation = Invitation.objects.create(invited_by=staff_user, email="nobundle@example.com")
    user = User.objects.create_user(email="nobundle@example.com", password="password", role=role)

    _account, _membership, entitlement = claim_invitation_for_user(
        invitation=invitation,
        user=user,
    )

    assert entitlement is None
    assert Entitlement.objects.count() == 0


def test_claim_invitation_creates_open_membership_when_none_exists(staff_user, role):
    invitation = Invitation.objects.create(
        invited_by=staff_user,
        email="newmembership@example.com",
        membership_role=AccountMembership.Role.GENERAL_USER,
    )
    user = User.objects.create_user(
        email="newmembership@example.com",
        password="password",
        role=role,
    )
    account = get_personal_account_for_user(user)
    AccountMembership.objects.filter(account=account, user=user).delete()

    _account, membership, _entitlement = claim_invitation_for_user(
        invitation=invitation,
        user=user,
    )

    assert membership.status == AccountMembership.Status.ACTIVE
    assert membership.role == AccountMembership.Role.GENERAL_USER
    assert membership.joined_at is not None


def test_claim_invitation_does_not_reuse_ended_membership(staff_user, role):
    invitation = Invitation.objects.create(
        invited_by=staff_user,
        email="ended@example.com",
        membership_role=AccountMembership.Role.GENERAL_USER,
    )
    user = User.objects.create_user(email="ended@example.com", password="password", role=role)
    account = get_personal_account_for_user(user)
    existing = AccountMembership.objects.get(account=account, user=user)
    existing.ended_at = timezone.now()
    existing.status = AccountMembership.Status.REMOVED
    existing.save(update_fields=["ended_at", "status", "updated_at"])

    _account, membership, _entitlement = claim_invitation_for_user(
        invitation=invitation,
        user=user,
    )

    assert membership.id != existing.id
    assert membership.status == AccountMembership.Status.ACTIVE
    assert membership.ended_at is None


def test_claim_invitation_preserves_existing_active_membership_role(staff_user, role):
    invitation = Invitation.objects.create(
        invited_by=staff_user,
        email="preserve@example.com",
        membership_role=AccountMembership.Role.GENERAL_USER,
    )
    user = User.objects.create_user(email="preserve@example.com", password="password", role=role)
    account = get_personal_account_for_user(user)
    membership = AccountMembership.objects.get(account=account, user=user)
    membership.role = AccountMembership.Role.INSTRUCTOR
    membership.status = AccountMembership.Status.SUSPENDED
    membership.invite_email = ""
    membership.invited_by = None
    membership.approved_by = None
    membership.joined_at = None
    membership.save(
        update_fields=[
            "role",
            "status",
            "invite_email",
            "invited_by",
            "approved_by",
            "joined_at",
            "updated_at",
        ]
    )

    _account, repaired, _entitlement = claim_invitation_for_user(
        invitation=invitation,
        user=user,
    )

    assert repaired.id == membership.id
    assert repaired.role == AccountMembership.Role.INSTRUCTOR
    assert repaired.status == AccountMembership.Status.ACTIVE
    assert repaired.invite_email == user.email
    assert repaired.invited_by == staff_user
    assert repaired.approved_by == staff_user
    assert repaired.joined_at is not None


def test_claim_invitation_does_not_rewrite_existing_repaired_membership_fields(staff_user, role):
    invitation = Invitation.objects.create(
        invited_by=staff_user,
        email="minimalrepair@example.com",
        membership_role=AccountMembership.Role.GENERAL_USER,
    )
    user = User.objects.create_user(email="minimalrepair@example.com", password="password", role=role)
    account = get_personal_account_for_user(user)
    membership = AccountMembership.objects.get(account=account, user=user)
    other_staff = User.objects.create_user(
        email="other-staff@example.com",
        password="password",
        role=role,
        is_staff=True,
    )
    joined_at = timezone.now() - timedelta(days=5)
    membership.role = AccountMembership.Role.INSTRUCTOR
    membership.status = AccountMembership.Status.ACTIVE
    membership.invite_email = "existing@example.com"
    membership.invited_by = other_staff
    membership.approved_by = other_staff
    membership.joined_at = joined_at
    membership.save(
        update_fields=[
            "role",
            "status",
            "invite_email",
            "invited_by",
            "approved_by",
            "joined_at",
            "updated_at",
        ]
    )

    _account, repaired, _entitlement = claim_invitation_for_user(
        invitation=invitation,
        user=user,
    )

    assert repaired.id == membership.id
    assert repaired.role == AccountMembership.Role.INSTRUCTOR
    assert repaired.status == AccountMembership.Status.ACTIVE
    assert repaired.invite_email == "existing@example.com"
    assert repaired.invited_by == other_staff
    assert repaired.approved_by == other_staff
    assert repaired.joined_at == joined_at


def test_claim_rejects_email_mismatch(staff_user, role):
    invitation = Invitation.objects.create(invited_by=staff_user, email="target@example.com")
    user = User.objects.create_user(email="other@example.com", password="password", role=role)

    with pytest.raises(InvitationEmailMismatchError):
        claim_invitation_for_user(invitation=invitation, user=user)


def test_claim_rejects_revoked_claimed_and_expired_tokens(staff_user, role):
    user = User.objects.create_user(email="reject@example.com", password="password", role=role)
    revoked = Invitation.objects.create(invited_by=staff_user, email="reject@example.com")
    revoke_invitation(invitation=revoked, revoked_by=staff_user)
    expired = Invitation.objects.create(
        invited_by=staff_user,
        email="reject@example.com",
        expires_at=timezone.now() - timedelta(days=1),
    )
    claimed = Invitation.objects.create(invited_by=staff_user, email="reject@example.com")
    Invitation.objects.filter(pk=claimed.pk).update(is_claimed=True, claimed_at=timezone.now())
    claimed.refresh_from_db()

    for invitation in (revoked, expired, claimed):
        with pytest.raises(InvitationNotClaimableError):
            claim_invitation_for_user(invitation=invitation, user=user)


def test_accept_view_claims_existing_authenticated_user(client, staff_user, role):
    invitation = Invitation.objects.create(invited_by=staff_user, email="existing@example.com")
    user = User.objects.create_user(email="existing@example.com", password="password", role=role)
    client.force_login(user)

    response = client.get(reverse("accounts:invitation-accept", kwargs={"token": invitation.token}))

    assert response.status_code == 302
    invitation.refresh_from_db()
    assert invitation.is_claimed is True
    assert invitation.claimed_by == user
    assert "invitation_token" not in client.session


def test_accept_view_email_mismatch_renders_mismatch_page(client, staff_user, role):
    invitation = Invitation.objects.create(invited_by=staff_user, email="target-view@example.com")
    user = User.objects.create_user(email="other-view@example.com", password="password", role=role)
    client.force_login(user)

    response = client.get(reverse("accounts:invitation-accept", kwargs={"token": invitation.token}))

    assert response.status_code == 403
    assert b"Use the invited email" in response.content
    assert "invitation_token" not in client.session


def test_accept_view_not_claimable_states_do_not_render_mismatch_page(
    client,
    staff_user,
    role,
):
    user = User.objects.create_user(email="state-view@example.com", password="password", role=role)
    revoked = Invitation.objects.create(invited_by=staff_user, email=user.email)
    revoke_invitation(invitation=revoked, revoked_by=staff_user)
    expired = Invitation.objects.create(
        invited_by=staff_user,
        email=user.email,
        expires_at=timezone.now() - timedelta(days=1),
    )
    claimed = Invitation.objects.create(invited_by=staff_user, email=user.email)
    Invitation.objects.filter(pk=claimed.pk).update(is_claimed=True, claimed_at=timezone.now())
    claimed.refresh_from_db()
    client.force_login(user)

    cases = (
        (revoked, b"Invitation unavailable"),
        (expired, b"Invitation expired"),
        (claimed, b"Invitation already claimed"),
    )
    for invitation, expected_text in cases:
        response = client.get(
            reverse("accounts:invitation-accept", kwargs={"token": invitation.token})
        )

        assert response.status_code == 410
        assert expected_text in response.content
        assert b"Use the invited email" not in response.content
        assert "invitation_token" not in client.session


def test_accept_view_invalid_token_renders_invalid_page(client):
    response = client.get(reverse("accounts:invitation-accept", kwargs={"token": "missing"}))

    assert response.status_code == 404
    assert b"Invitation unavailable" in response.content


def test_accept_view_routes_existing_email_to_login(client, staff_user, role):
    user = User.objects.create_user(email="loginclaim@example.com", password="password", role=role)
    invitation = Invitation.objects.create(invited_by=staff_user, email=user.email)

    response = client.get(reverse("accounts:invitation-accept", kwargs={"token": invitation.token}))

    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))
    assert client.session["invitation_token"] == invitation.token


def test_accept_view_routes_new_email_to_signup_and_keeps_session_token(client, staff_user):
    invitation = Invitation.objects.create(invited_by=staff_user, email="newsignup@example.com")

    response = client.get(reverse("accounts:invitation-accept", kwargs={"token": invitation.token}))

    assert response.status_code == 302
    assert response.url == reverse("account_signup")
    assert client.session["invitation_token"] == invitation.token


def test_legacy_invite_urls_redirect_to_staff_destinations(client, staff_user):
    invitation = Invitation.objects.create(invited_by=staff_user, email="claimed@example.com")
    client.force_login(staff_user)

    list_response = client.get(reverse("accounts:list-invites"))
    new_response = client.get(reverse("accounts:new-invite"))
    success_response = client.get(
        reverse("accounts:invite-success", kwargs={"token": invitation.token})
    )

    assert list_response.status_code == 302
    assert list_response.url == reverse("staff:invitation-list")
    assert new_response.status_code == 302
    assert new_response.url == reverse("staff:invitation-create")
    assert success_response.status_code == 302
    assert success_response.url == reverse("staff:invitation-detail", kwargs={"invitation_id": invitation.id})


def test_staff_dashboard_permissions_and_invitation_filter(client, staff_user, regular_user):
    Invitation.objects.create(
        invited_by=staff_user,
        email="bundle-list@example.com",
        product_code=ProductCode.CHATLAB_GO.value,
    )

    client.force_login(regular_user)
    assert client.get(reverse("staff:invitation-list")).status_code == 403

    client.force_login(staff_user)
    response = client.get(reverse("staff:invitation-list"), {"has_bundle": "true"})

    assert response.status_code == 200
    assert b"bundle-list@example.com" in response.content
    assert b"Product Access Bundle" in response.content


def test_header_shows_staff_menu_only_for_staff(client, staff_user, regular_user):
    client.force_login(staff_user)
    staff_response = client.get(reverse("home"))
    assert b"Staff" in staff_response.content
    assert reverse("staff:invitation-list").encode() in staff_response.content
    assert reverse("feedback:staff-list").encode() in staff_response.content

    client.force_login(regular_user)
    user_response = client.get(reverse("home"))
    assert reverse("staff:invitation-list").encode() not in user_response.content
    assert reverse("feedback:staff-list").encode() not in user_response.content


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_invitation_emails_use_environment_hint_for_staging_and_production(staff_user):
    invitation = Invitation.objects.create(invited_by=staff_user, email="envhint@example.com")
    send_invitation_email_task.run(invitation.id, "staging")
    assert "https://medsim-staging.jackfruitco.com/accounts/invitations/accept/" in mail.outbox[0].body

    invitation.rotate_token_and_extend_expiry()
    send_invitation_email_task.run(invitation.id, "production")
    assert "https://medsim.jackfruitco.com/accounts/invitations/accept/" in mail.outbox[1].body


def test_staff_create_and_resend_pass_request_environment_hint(
    client,
    staff_user,
    monkeypatch,
):
    captured = []

    def _capture_delay(invitation_id, environment_hint):
        captured.append((invitation_id, environment_hint))

    monkeypatch.setattr("apps.accounts.tasks.send_invitation_email_task.delay", _capture_delay)
    client.force_login(staff_user)
    create_response = client.post(
        reverse("staff:invitation-create"),
        {
            "email": "staging-create@example.com",
            "first_name": "",
            "product_code": "",
            "membership_role": AccountMembership.Role.GENERAL_USER,
        },
        HTTP_HOST="medsim-staging.jackfruitco.com",
    )
    assert create_response.status_code == 302
    created = Invitation.objects.get(email="staging-create@example.com")
    assert captured[-1] == (created.id, "staging")

    resend_response = client.post(
        reverse("staff:invitation-resend", kwargs={"invitation_id": created.id}),
        HTTP_HOST="medsim-staging.jackfruitco.com",
    )
    assert resend_response.status_code == 302
    assert captured[-1][1] == "staging"


def test_superuser_manual_product_access_grant_from_user_dashboard(
    client,
    superuser,
    regular_user,
):
    account = get_personal_account_for_user(regular_user)
    client.force_login(superuser)

    response = client.post(
        reverse("staff:user-detail", kwargs={"user_id": regular_user.id}),
        {"account_id": str(account.id), "product_code": ProductCode.CHATLAB_GO.value},
    )

    assert response.status_code == 302
    assert Entitlement.objects.filter(
        account=account,
        subject_user=regular_user,
        product_code=ProductCode.CHATLAB_GO.value,
    ).exists()
