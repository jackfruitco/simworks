from __future__ import annotations

import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import Account, AccountMembership
from apps.accounts.services.accounts import create_account_audit_event

User = get_user_model()


def _normalized_email(value: str) -> str:
    return (value or "").strip().lower()


def _build_unique_account_slug(value: str) -> str:
    base = slugify(value)[:88] or f"account-{uuid.uuid4().hex[:8]}"
    candidate = base
    suffix = 2
    while Account.objects.filter(slug=candidate).exists():
        candidate = f"{base[: max(1, 96 - len(str(suffix)))]}-{suffix}"
        suffix += 1
    return candidate


def list_accounts_for_user(user):
    return (
        Account.objects.filter(
            Q(owner_user=user, account_type=Account.AccountType.PERSONAL)
            | Q(
                memberships__user=user,
                memberships__status=AccountMembership.Status.ACTIVE,
                memberships__ended_at__isnull=True,
            )
        )
        .distinct()
        .order_by("name", "id")
    )


@transaction.atomic
def create_organization_account(
    *,
    name: str,
    owner_user,
    slug: str = "",
    requires_join_approval: bool = False,
    parent_account: Account | None = None,
) -> Account:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValidationError("Organization name is required")
    if parent_account and parent_account.account_type != Account.AccountType.ORGANIZATION:
        raise ValidationError("Parent account must be an organization")

    account = Account.objects.create(
        name=normalized_name,
        slug=_build_unique_account_slug(slug or normalized_name),
        account_type=Account.AccountType.ORGANIZATION,
        parent_account=parent_account,
        requires_join_approval=requires_join_approval,
        is_active=True,
    )
    AccountMembership.objects.create(
        account=account,
        user=owner_user,
        invite_email=_normalized_email(getattr(owner_user, "email", "")),
        role=AccountMembership.Role.ORG_ADMIN,
        status=AccountMembership.Status.ACTIVE,
        approved_by=owner_user,
        joined_at=timezone.now(),
    )
    create_account_audit_event(
        account=account,
        actor_user=owner_user,
        event_type="account.created",
        target_ref=f"account:{account.pk}",
        metadata={"account_type": account.account_type},
    )
    return account


@transaction.atomic
def invite_account_member(
    *,
    account: Account,
    email: str,
    role: str,
    invited_by,
) -> AccountMembership:
    if account.account_type != Account.AccountType.ORGANIZATION:
        raise ValidationError("Only organization accounts support invitations")

    normalized_email = _normalized_email(email)
    if not normalized_email:
        raise ValidationError("Invite email is required")
    valid_roles = {choice for choice, _label in AccountMembership.Role.choices}
    if role not in valid_roles:
        raise ValidationError("Invalid membership role")

    target_user = User.objects.filter(email__iexact=normalized_email, is_active=True).first()
    membership = None
    if target_user is not None:
        membership = (
            AccountMembership.objects.filter(
                account=account,
                user=target_user,
                ended_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
    if membership is None:
        membership = (
            AccountMembership.objects.filter(
                account=account,
                invite_email=normalized_email,
                ended_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

    if membership is None:
        membership = AccountMembership.objects.create(
            account=account,
            user=target_user,
            invite_email=normalized_email,
            role=role,
            status=AccountMembership.Status.PENDING,
            invited_by=invited_by,
        )
    else:
        membership.user = target_user or membership.user
        membership.invite_email = normalized_email
        membership.role = role
        membership.status = AccountMembership.Status.PENDING
        membership.invited_by = invited_by
        membership.ended_at = None
        membership.save(
            update_fields=[
                "user",
                "invite_email",
                "role",
                "status",
                "invited_by",
                "ended_at",
                "updated_at",
            ]
        )

    create_account_audit_event(
        account=account,
        actor_user=invited_by,
        event_type="membership.invited",
        target_ref=f"membership:{membership.pk}",
        metadata={"invite_email": normalized_email, "role": role},
    )
    return membership


@transaction.atomic
def approve_account_membership(*, membership: AccountMembership, approved_by) -> AccountMembership:
    if membership.account.account_type != Account.AccountType.ORGANIZATION:
        raise ValidationError("Only organization memberships can be approved")

    if membership.user_id is None and membership.invite_email:
        membership.user = User.objects.filter(
            email__iexact=membership.invite_email,
            is_active=True,
        ).first()
    if membership.user_id is None:
        raise ValidationError("Membership is not yet linked to a user")

    membership.status = AccountMembership.Status.ACTIVE
    membership.approved_by = approved_by
    membership.joined_at = membership.joined_at or timezone.now()
    membership.ended_at = None
    membership.save(
        update_fields=[
            "user",
            "status",
            "approved_by",
            "joined_at",
            "ended_at",
            "updated_at",
        ]
    )

    create_account_audit_event(
        account=membership.account,
        actor_user=approved_by,
        event_type="membership.approved",
        target_ref=f"membership:{membership.pk}",
        metadata={"user_id": membership.user_id, "role": membership.role},
    )
    return membership
