from __future__ import annotations

import logging

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    Account,
    AccountMembership,
    Invitation,
    InvitationAuditEvent,
)
from apps.accounts.services.accounts import (
    create_account_audit_event,
    maybe_create_personal_account_for_user,
)
from apps.billing.catalog import is_valid_product_code
from apps.billing.models import Entitlement
from apps.billing.services.entitlements import grant_manual_product_entitlement
from apps.common.emailing.environment import get_email_environment_label, is_staging_email_context

logger = logging.getLogger(__name__)
User = get_user_model()


class InvitationClaimError(Exception):
    def __init__(
        self,
        message: str,
        *,
        invitation: Invitation | None = None,
        reason: str = "",
    ):
        super().__init__(message)
        self.invitation = invitation
        self.reason = reason


class InvitationEmailMismatchError(InvitationClaimError):
    pass


class InvitationNotClaimableError(InvitationClaimError):
    pass


def normalize_email(value: str | None) -> str:
    return Invitation.normalize_email(value)


def create_invitation_audit_event(
    *,
    invitation: Invitation,
    event_type: str,
    actor_user=None,
    metadata: dict | None = None,
) -> InvitationAuditEvent:
    return InvitationAuditEvent.objects.create(
        invitation=invitation,
        actor_user=actor_user,
        event_type=event_type,
        metadata=metadata or {},
    )


def _validate_staff(user, *, action: str) -> None:
    if not getattr(user, "is_staff", False):
        raise PermissionDenied(f"Only staff may {action} invitations.")


def _validate_product_code_actor(user, product_code: str) -> str:
    product_code = (product_code or "").strip()
    if not product_code:
        return ""
    if not getattr(user, "is_superuser", False):
        raise PermissionDenied("Only superusers may attach a Product Access Bundle.")
    if not is_valid_product_code(product_code):
        raise ValidationError({"product_code": "Enter a valid Product Access Bundle."})
    return product_code


def _validate_membership_role(membership_role: str) -> str:
    role = membership_role or AccountMembership.Role.GENERAL_USER
    valid_roles = {choice for choice, _label in AccountMembership.Role.choices}
    if role not in valid_roles:
        raise ValidationError({"membership_role": "Enter a valid account membership role."})
    return role


def _primary_email_for_user(user) -> str:
    email_address = (
        EmailAddress.objects.filter(user=user, primary=True).order_by("-verified", "id").first()
    )
    if email_address is not None:
        return normalize_email(email_address.email)
    return normalize_email(getattr(user, "email", ""))


def _assert_email_matches_invitation(*, invitation: Invitation, user) -> None:
    invited_email = normalize_email(invitation.email)
    if not invited_email:
        return
    if _primary_email_for_user(user) != invited_email:
        raise InvitationEmailMismatchError(
            "This invitation is for a different email address.",
            invitation=invitation,
            reason="email_mismatch",
        )


def _source_ref_for_invitation(invitation: Invitation, product_code: str) -> str:
    return f"invitation:{invitation.uuid}:{product_code}"


def _not_claimable_reason(invitation: Invitation) -> str:
    if invitation.revoked_at:
        return "revoked"
    if invitation.is_claimed:
        return "claimed"
    if invitation.is_expired:
        return "expired"
    return "not_claimable"


def _raise_not_claimable(invitation: Invitation) -> None:
    reason = _not_claimable_reason(invitation)
    raise InvitationNotClaimableError(
        "This invitation can no longer be claimed.",
        invitation=invitation,
        reason=reason,
    )


@transaction.atomic
def create_invitation(
    *,
    invited_by,
    email: str,
    first_name: str = "",
    product_code: str = "",
    membership_role: str = AccountMembership.Role.GENERAL_USER,
    environment_hint: str | None = None,
) -> Invitation:
    _validate_staff(invited_by, action="create")
    product_code = _validate_product_code_actor(invited_by, product_code)
    membership_role = _validate_membership_role(membership_role)

    invitation = Invitation(
        invited_by=invited_by,
        email=normalize_email(email) or None,
        first_name=(first_name or "").strip() or None,
        product_code=product_code,
        membership_role=membership_role,
    )
    invitation.full_clean()
    invitation.save()
    create_invitation_audit_event(
        invitation=invitation,
        actor_user=invited_by,
        event_type="invitation.created",
        metadata={
            "email": invitation.email or "",
            "first_name": invitation.first_name or "",
            "product_code": product_code,
            "membership_role": membership_role,
        },
    )
    queue_invitation_email(invitation=invitation, environment_hint=environment_hint)
    return invitation


@transaction.atomic
def resend_invitation(
    *,
    invitation: Invitation,
    resent_by,
    environment_hint: str | None = None,
) -> Invitation:
    _validate_staff(resent_by, action="resend")
    invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
    if invitation.is_claimed:
        raise ValidationError("Claimed invitations cannot be resent.")
    if invitation.revoked_at:
        raise ValidationError("Revoked invitations cannot be resent.")

    invitation.rotate_token_and_extend_expiry()
    create_invitation_audit_event(
        invitation=invitation,
        actor_user=resent_by,
        event_type="invitation.resent",
        metadata={"expires_at": invitation.expires_at.isoformat() if invitation.expires_at else ""},
    )
    queue_invitation_email(invitation=invitation, environment_hint=environment_hint)
    return invitation


def queue_invitation_email(
    *,
    invitation: Invitation,
    environment_hint: str | None = None,
) -> None:
    if not invitation.email:
        return

    def _enqueue() -> None:
        from apps.accounts.tasks import send_invitation_email_task

        send_invitation_email_task.delay(invitation.id, environment_hint)

    transaction.on_commit(_enqueue)


def get_invitation_by_token_for_claim(token) -> Invitation:
    token = (token or "").strip()
    if not token:
        raise Invitation.DoesNotExist
    invitation = Invitation.objects.select_related("invited_by", "claimed_by").get(token=token)
    if not invitation.may_be_claimed():
        _raise_not_claimable(invitation)
    return invitation


def claim_invitation_for_user(
    *,
    invitation: Invitation,
    user,
    request=None,
) -> tuple[Account, AccountMembership, Entitlement | None]:
    environment_hint = get_email_environment_label(request=request)
    del request
    if not getattr(user, "is_authenticated", True):
        raise InvitationClaimError("A signed-in user is required to claim an invitation.")
    if not getattr(user, "pk", None):
        raise ValidationError("User must be saved before claiming an invitation.")

    with transaction.atomic():
        invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
        if not invitation.may_be_claimed():
            _raise_not_claimable(invitation)
        _assert_email_matches_invitation(invitation=invitation, user=user)

        account = maybe_create_personal_account_for_user(user)
        # Invitation claims are personal-account-only in this phase. A successful
        # claim must leave the user with one active membership to their personal
        # account, but invitation creation never creates a pending membership.
        # If the personal membership already exists, repair only the fields
        # needed to make it active and attributable to the invite claim; avoid
        # broadly rewriting unrelated relationship data. If the personal account
        # helper had to bootstrap the membership during this claim, treat that
        # as invite-created and apply the invitation's membership role.
        membership = (
            AccountMembership.objects.select_for_update()
            .filter(account=account, user=user, ended_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        membership_created = membership is None
        if membership is None:
            membership = AccountMembership.objects.create(
                account=account,
                user=user,
                invite_email=normalize_email(getattr(user, "email", "")),
                role=invitation.membership_role,
                status=AccountMembership.Status.ACTIVE,
                invited_by=invitation.invited_by,
                approved_by=invitation.invited_by,
                joined_at=timezone.now(),
            )
        else:
            update_fields = []
            user_email = normalize_email(getattr(user, "email", ""))
            if not membership.invite_email and user_email:
                membership.invite_email = user_email
                update_fields.append("invite_email")
            if not membership.role:
                membership.role = invitation.membership_role
                update_fields.append("role")
            if membership.status != AccountMembership.Status.ACTIVE:
                membership.status = AccountMembership.Status.ACTIVE
                update_fields.append("status")
            if membership.joined_at is None:
                membership.joined_at = timezone.now()
                update_fields.append("joined_at")
            if membership.invited_by_id is None and invitation.invited_by_id is not None:
                membership.invited_by = invitation.invited_by
                update_fields.append("invited_by")
            if membership.approved_by_id is None and invitation.invited_by_id is not None:
                membership.approved_by = invitation.invited_by
                update_fields.append("approved_by")
            if update_fields:
                membership.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])

        entitlement = None
        if invitation.product_code:
            entitlement = grant_manual_product_entitlement(
                user,
                account,
                invitation.product_code,
                source_ref=_source_ref_for_invitation(invitation, invitation.product_code),
            )

        invitation.mark_as_claimed(user=user, account=account)

        create_account_audit_event(
            account=account,
            actor_user=user,
            event_type="invitation.claimed",
            target_type="invitation",
            target_ref=str(invitation.uuid),
            metadata={"invitation_id": invitation.id, "email": invitation.email or ""},
        )
        create_account_audit_event(
            account=account,
            actor_user=invitation.invited_by,
            event_type="account.membership_created_from_invitation",
            target_type="account_membership",
            target_ref=str(membership.uuid),
            metadata={
                "invitation_id": invitation.id,
                "user_id": user.id,
                "membership_id": membership.id,
                "created": membership_created,
                "role": membership.role,
            },
        )
        if entitlement is not None:
            create_account_audit_event(
                account=account,
                actor_user=invitation.invited_by,
                event_type="entitlement.granted_from_invitation",
                target_type="entitlement",
                target_ref=str(entitlement.uuid),
                metadata={
                    "invitation_id": invitation.id,
                    "product_code": entitlement.product_code,
                    "source_ref": entitlement.source_ref,
                },
            )
        maybe_send_staging_account_ready_email(
            invitation=invitation,
            environment_hint=environment_hint,
        )
        return account, membership, entitlement


def audit_invitation_send_failure(*, invitation: Invitation, error: Exception) -> None:
    logger.exception("Invitation email send failed", extra={"invitation_id": invitation.id})
    create_invitation_audit_event(
        invitation=invitation,
        actor_user=None,
        event_type="invitation.send_failed",
        metadata={"error": str(error)},
    )


def audit_invitation_sent(*, invitation: Invitation) -> None:
    create_invitation_audit_event(
        invitation=invitation,
        actor_user=None,
        event_type="invitation.sent",
        metadata={"send_count": invitation.send_count},
    )


def maybe_send_staging_account_ready_email(
    *,
    invitation: Invitation,
    environment_hint: str | None = None,
) -> None:
    if not is_staging_email_context(environment_hint=environment_hint):
        return
    if not invitation.email:
        return
    if invitation.staging_setup_reminder_sent_at is not None:
        return

    def _enqueue() -> None:
        from apps.accounts.tasks import send_staging_account_ready_email_task

        send_staging_account_ready_email_task.delay(invitation.id, environment_hint)

    transaction.on_commit(_enqueue)


def revoke_invitation(*, invitation: Invitation, revoked_by) -> Invitation:
    _validate_staff(revoked_by, action="revoke")
    with transaction.atomic():
        invitation = Invitation.objects.select_for_update().get(pk=invitation.pk)
        if invitation.is_claimed:
            raise ValidationError("Claimed invitations cannot be revoked.")
        invitation.mark_revoked()
        create_invitation_audit_event(
            invitation=invitation,
            actor_user=revoked_by,
            event_type="invitation.revoked",
            metadata={},
        )
    return invitation
