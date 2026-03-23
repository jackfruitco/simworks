from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Account, AccountAuditEvent, AccountMembership


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _personal_account_name(user) -> str:
    display_name = user.get_full_name().strip() or user.email or f"user-{user.pk}"
    return f"{display_name} Personal"


def _personal_account_slug(user) -> str:
    return f"personal-{user.pk}"


@transaction.atomic
def maybe_create_personal_account_for_user(user):
    if not getattr(user, "pk", None):
        raise ValueError("User must be saved before creating a personal account.")

    account = (
        Account.objects.select_for_update()
        .filter(owner_user=user, account_type=Account.AccountType.PERSONAL)
        .first()
    )
    if account is None:
        account = Account.objects.create(
            name=_personal_account_name(user),
            slug=_personal_account_slug(user),
            account_type=Account.AccountType.PERSONAL,
            owner_user=user,
        )

    membership, created = AccountMembership.objects.get_or_create(
        account=account,
        user=user,
        ended_at__isnull=True,
        defaults={
            "invite_email": user.email or "",
            "role": AccountMembership.Role.ORG_ADMIN,
            "status": AccountMembership.Status.ACTIVE,
            "joined_at": timezone.now(),
        },
    )
    if not created:
        update_fields = []
        if membership.invite_email != (user.email or ""):
            membership.invite_email = user.email or ""
            update_fields.append("invite_email")
        if membership.status != AccountMembership.Status.ACTIVE:
            membership.status = AccountMembership.Status.ACTIVE
            update_fields.append("status")
        if membership.role != AccountMembership.Role.ORG_ADMIN:
            membership.role = AccountMembership.Role.ORG_ADMIN
            update_fields.append("role")
        if membership.joined_at is None:
            membership.joined_at = timezone.now()
            update_fields.append("joined_at")
        if membership.ended_at is not None:
            membership.ended_at = None
            update_fields.append("ended_at")
        if update_fields:
            membership.save(update_fields=update_fields)

    if user.active_account_id != account.id:
        user.active_account = account
        user.save(update_fields=["active_account"])

    return account


@transaction.atomic
def maybe_claim_pending_memberships_for_user(user):
    email = _normalized_email(user.email)
    if not email:
        return []

    claimed = []
    memberships = (
        AccountMembership.objects.select_for_update()
        .filter(user__isnull=True, ended_at__isnull=True, invite_email__iexact=email)
        .select_related("account")
    )
    for membership in memberships:
        membership.user = user
        update_fields = ["user"]
        if membership.status == AccountMembership.Status.ACTIVE and membership.joined_at is None:
            membership.joined_at = timezone.now()
            update_fields.append("joined_at")
        membership.save(update_fields=update_fields)
        claimed.append(membership)
    return claimed


def get_personal_account_for_user(user):
    account = Account.objects.filter(
        owner_user=user,
        account_type=Account.AccountType.PERSONAL,
    ).first()
    if account is None:
        account = maybe_create_personal_account_for_user(user)
    return account


def get_default_account_for_user(user):
    if getattr(user, "active_account_id", None):
        return user.active_account
    return get_personal_account_for_user(user)


def maybe_set_active_account_for_user(user, account):
    if user.active_account_id == account.id:
        return account
    user.active_account = account
    user.save(update_fields=["active_account"])
    return account


def create_account_audit_event(
    *,
    account,
    event_type: str,
    actor_user=None,
    target_type: str = "",
    target_ref: str = "",
    metadata: dict | None = None,
):
    return AccountAuditEvent.objects.create(
        account=account,
        actor_user=actor_user,
        event_type=event_type,
        target_type=target_type,
        target_ref=target_ref,
        metadata=metadata or {},
    )
