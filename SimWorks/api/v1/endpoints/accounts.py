from __future__ import annotations

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from api.v1.auth import DualAuth
from api.v1.schemas.accounts import (
    AccessSnapshotOut,
    AccountOut,
    AccountSelectIn,
    MembershipInviteIn,
    MembershipOut,
    OrganizationCreateIn,
    ProductAccessOut,
)
from api.v1.schemas.billing import (
    BillingAccountOut,
    BillingSummaryOut,
    EntitlementOut,
    SubscriptionOut,
)
from api.v1.utils import get_account_for_request
from apps.accounts.models import Account, AccountMembership
from apps.accounts.permissions import (
    can_access_account,
    can_manage_billing,
    can_manage_members,
    get_account_membership,
)
from apps.accounts.services import (
    approve_account_membership,
    create_organization_account,
    get_default_account_for_user,
    invite_account_member,
    list_accounts_for_user,
    maybe_create_personal_account_for_user,
    maybe_set_active_account_for_user,
)
from apps.billing.models import BillingAccount, Entitlement, Subscription
from apps.billing.services.entitlements import get_access_snapshot

router = Router(tags=["accounts"], auth=DualAuth())


def _account_to_out(account, *, user, active_account_id=None) -> AccountOut:
    membership = get_account_membership(user, account)
    return AccountOut(
        uuid=str(account.uuid),
        name=account.name,
        slug=account.slug,
        account_type=account.account_type,
        is_active=account.is_active,
        requires_join_approval=account.requires_join_approval,
        parent_account_uuid=str(account.parent_account.uuid) if account.parent_account_id else None,
        membership_role=membership.role if membership else "",
        membership_status=membership.status if membership else "",
        is_active_context=account.id == active_account_id,
    )


def _membership_to_out(membership: AccountMembership) -> MembershipOut:
    return MembershipOut(
        uuid=str(membership.uuid),
        account_uuid=str(membership.account.uuid),
        user_id=membership.user_id,
        invite_email=membership.invite_email,
        role=membership.role,
        status=membership.status,
        joined_at=membership.joined_at,
        ended_at=membership.ended_at,
    )


def _access_snapshot_to_out(snapshot: dict) -> AccessSnapshotOut:
    return AccessSnapshotOut(
        account_uuid=snapshot.get("account_uuid", ""),
        account_name=snapshot.get("account_name", ""),
        account_type=snapshot.get("account_type", ""),
        membership_role=snapshot.get("membership_role", ""),
        products={
            code: ProductAccessOut(**details)
            for code, details in (snapshot.get("products") or {}).items()
        },
    )


@router.get("/", response=list[AccountOut], summary="List accessible accounts")
def list_accounts(request: HttpRequest) -> list[AccountOut]:
    user = request.auth
    maybe_create_personal_account_for_user(user)
    active_account = get_default_account_for_user(user)
    return [
        _account_to_out(account, user=user, active_account_id=getattr(active_account, "id", None))
        for account in list_accounts_for_user(user)
    ]


@router.post("/select/", response=AccountOut, summary="Select active account context")
def select_account(request: HttpRequest, body: AccountSelectIn) -> AccountOut:
    user = request.auth
    account = Account.objects.filter(uuid=body.account_uuid, is_active=True).first()
    if account is None or not can_access_account(user, account):
        raise HttpError(404, "Account not found")
    maybe_set_active_account_for_user(user, account)
    return _account_to_out(account, user=user, active_account_id=account.id)


@router.post("/organizations/", response={201: AccountOut}, summary="Create organization account")
def create_organization(request: HttpRequest, body: OrganizationCreateIn) -> tuple[int, AccountOut]:
    user = request.auth
    parent_account = None
    if body.parent_account_uuid:
        parent_account = Account.objects.filter(
            uuid=body.parent_account_uuid, is_active=True
        ).first()
        if parent_account is None or not can_manage_members(user, parent_account):
            raise HttpError(403, "Parent account management access required")
    try:
        account = create_organization_account(
            name=body.name,
            owner_user=user,
            slug=body.slug,
            requires_join_approval=body.requires_join_approval,
            parent_account=parent_account,
        )
    except ValidationError as exc:
        raise HttpError(400, str(exc)) from None
    return 201, _account_to_out(
        account, user=user, active_account_id=getattr(user.active_account, "id", None)
    )


@router.get("/me/access/", response=AccessSnapshotOut, summary="Get current access snapshot")
def current_access_snapshot(request: HttpRequest) -> AccessSnapshotOut:
    user = request.auth
    account = get_account_for_request(request, user)
    return _access_snapshot_to_out(get_access_snapshot(user, account))


@router.get(
    "/memberships/", response=list[MembershipOut], summary="List memberships for current account"
)
def list_memberships(request: HttpRequest) -> list[MembershipOut]:
    user = request.auth
    account = get_account_for_request(request, user)
    queryset = AccountMembership.objects.filter(account=account).select_related("account", "user")
    if not can_manage_members(user, account):
        queryset = queryset.filter(user=user)
    return [_membership_to_out(membership) for membership in queryset.order_by("-created_at")]


@router.post(
    "/memberships/invite/",
    response={201: MembershipOut},
    summary="Invite a member to the current account",
)
def invite_membership(
    request: HttpRequest,
    body: MembershipInviteIn,
) -> tuple[int, MembershipOut]:
    user = request.auth
    account = get_account_for_request(request, user)
    if not can_manage_members(user, account):
        raise HttpError(403, "Member management access required")
    try:
        membership = invite_account_member(
            account=account,
            email=body.email,
            role=body.role,
            invited_by=user,
        )
    except ValidationError as exc:
        raise HttpError(400, str(exc)) from None
    return 201, _membership_to_out(membership)


@router.post(
    "/memberships/{membership_uuid}/approve/",
    response=MembershipOut,
    summary="Approve a pending membership",
)
def approve_membership(request: HttpRequest, membership_uuid: str) -> MembershipOut:
    user = request.auth
    account = get_account_for_request(request, user)
    if not can_manage_members(user, account):
        raise HttpError(403, "Member management access required")
    membership = (
        AccountMembership.objects.select_related("account", "user")
        .filter(uuid=membership_uuid, account=account)
        .first()
    )
    if membership is None:
        raise HttpError(404, "Membership not found")
    try:
        membership = approve_account_membership(membership=membership, approved_by=user)
    except ValidationError as exc:
        raise HttpError(400, str(exc)) from None
    return _membership_to_out(membership)


@router.get(
    "/billing-summary/",
    response=BillingSummaryOut,
    summary="Get billing summary for the current account",
)
def billing_summary(request: HttpRequest) -> BillingSummaryOut:
    user = request.auth
    account = get_account_for_request(request, user)
    if not can_manage_billing(user, account):
        raise HttpError(403, "Billing management access required")

    billing_accounts = BillingAccount.objects.filter(account=account).order_by(
        "provider_type", "id"
    )
    subscriptions = Subscription.objects.filter(account=account).order_by("-created_at")
    entitlements = Entitlement.objects.filter(account=account).order_by(
        "product_code", "created_at"
    )
    return BillingSummaryOut(
        account_uuid=str(account.uuid),
        billing_accounts=[
            BillingAccountOut(
                uuid=str(item.uuid),
                provider_type=item.provider_type,
                provider_customer_id=item.provider_customer_id,
                billing_email=item.billing_email,
                country_code=item.country_code,
                is_active=item.is_active,
            )
            for item in billing_accounts
        ],
        subscriptions=[
            SubscriptionOut(
                uuid=str(item.uuid),
                provider_type=item.provider_type,
                plan_code=item.plan_code,
                status=item.status,
                provider_subscription_id=item.provider_subscription_id,
                provider_original_transaction_id=item.provider_original_transaction_id,
                cancel_at_period_end=item.cancel_at_period_end,
                current_period_end=item.current_period_end,
            )
            for item in subscriptions
        ],
        entitlements=[
            EntitlementOut(
                uuid=str(item.uuid),
                source_type=item.source_type,
                source_ref=item.source_ref,
                scope_type=item.scope_type,
                subject_user_id=item.subject_user_id,
                product_code=item.product_code,
                feature_code=item.feature_code,
                limit_code=item.limit_code,
                limit_value=item.limit_value,
                status=item.status,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
            )
            for item in entitlements
        ],
    )
