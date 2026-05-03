"""Database safety and validation helpers for core restores."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.management.commands.seed_roles import SYSTEM_USERS
from apps.accounts.models import Account, AccountMembership, Invitation, User
from apps.billing.models import BillingAccount, Entitlement, SeatAssignment, Subscription

from .inventory import CORE_BUSINESS_TABLES, CORE_TRUNCATE_TABLES

SYSTEM_USER_EMAILS = {entry["email"] for entry in SYSTEM_USERS}


@dataclass(frozen=True)
class BusinessDataCheck:
    non_empty_tables: tuple[str, ...]
    non_seed_user_count: int

    @property
    def has_business_data(self) -> bool:
        return bool(self.non_empty_tables or self.non_seed_user_count)


def quote_table(table: str) -> str:
    return connection.ops.quote_name(table)


def table_count(table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {quote_table(table)}")
        return int(cursor.fetchone()[0])


def check_no_business_data() -> BusinessDataCheck:
    ignored_seed_tables = {
        "accounts_user",
        "accounts_userrole",
        "accounts_roleresource",
        "accounts_account",
        "accounts_accountmembership",
        "django_site",
        "django_content_type",
        "auth_permission",
    }
    non_empty: list[str] = []
    for table in CORE_BUSINESS_TABLES:
        if table in ignored_seed_tables:
            continue
        if table_count(table):
            non_empty.append(table)

    non_seed_user_count = User.objects.exclude(email__in=SYSTEM_USER_EMAILS).count()
    if Account.objects.exclude(owner_user__email__in=SYSTEM_USER_EMAILS).exists():
        non_empty.append("accounts_account")
    if AccountMembership.objects.exclude(user__email__in=SYSTEM_USER_EMAILS).exists():
        non_empty.append("accounts_accountmembership")
    return BusinessDataCheck(
        non_empty_tables=tuple(non_empty),
        non_seed_user_count=non_seed_user_count,
    )


def truncate_core_tables() -> None:
    table_sql = ", ".join(quote_table(table) for table in CORE_TRUNCATE_TABLES)
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table_sql} RESTART IDENTITY CASCADE")


def expire_pending_invitations_after_restore() -> int:
    with transaction.atomic():
        restored_at = timezone.now()
        return Invitation.objects.select_for_update().filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=restored_at),
            is_claimed=False,
            revoked_at__isnull=True,
        ).update(expires_at=restored_at)


def validate_core_restore() -> list[str]:
    errors: list[str] = []

    duplicate_emails = User.objects.values("email").order_by().annotate(count=Count("id")).filter(
        count__gt=1
    )
    if duplicate_emails.exists():
        errors.append("Duplicate user emails exist.")

    users_without_roles = User.objects.filter(role__isnull=True).count()
    if users_without_roles:
        errors.append(f"{users_without_roles} users are missing roles.")

    users_without_personal_accounts = User.objects.exclude(email__in=SYSTEM_USER_EMAILS).exclude(
        owned_accounts__account_type=Account.AccountType.PERSONAL
    )
    if users_without_personal_accounts.exists():
        errors.append("One or more non-system users are missing personal accounts.")

    invalid_memberships = AccountMembership.objects.filter(account__isnull=True).count()
    if invalid_memberships:
        errors.append(f"{invalid_memberships} memberships are missing accounts.")

    invalid_billing_accounts = BillingAccount.objects.filter(account__isnull=True).count()
    if invalid_billing_accounts:
        errors.append(f"{invalid_billing_accounts} billing accounts are missing accounts.")

    invalid_subscriptions = Subscription.objects.filter(account__isnull=True).count()
    if invalid_subscriptions:
        errors.append(f"{invalid_subscriptions} subscriptions are missing accounts.")

    invalid_entitlements = Entitlement.objects.filter(account__isnull=True).count()
    if invalid_entitlements:
        errors.append(f"{invalid_entitlements} entitlements are missing accounts.")

    invalid_user_entitlements = Entitlement.objects.filter(
        scope_type=Entitlement.ScopeType.USER,
        subject_user__isnull=True,
    ).count()
    if invalid_user_entitlements:
        errors.append(f"{invalid_user_entitlements} user-scoped entitlements have no user.")

    invalid_seat_assignments = SeatAssignment.objects.filter(
        ended_at__isnull=True,
        user__isnull=True,
    ).count()
    if invalid_seat_assignments:
        errors.append(f"{invalid_seat_assignments} active seat assignments have no user.")

    missing_sites = table_count("django_site") == 0
    if missing_sites:
        errors.append("No django_site rows exist.")

    return errors


def raise_if_core_restore_invalid() -> None:
    errors = validate_core_restore()
    if errors:
        raise CommandError("Core restore validation failed: " + "; ".join(errors))
