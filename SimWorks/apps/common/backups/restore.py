"""Database safety and validation helpers for core restores."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.management.commands.seed_roles import SYSTEM_USERS
from apps.accounts.models import Account, AccountMembership, Invitation, User
from apps.billing.models import BillingAccount, Entitlement, SeatAssignment, Subscription

from .inventory import CORE_BACKUP_TABLES, CORE_BUSINESS_TABLES

SYSTEM_USER_EMAILS = {entry["email"] for entry in SYSTEM_USERS}


@dataclass(frozen=True)
class BusinessDataCheck:
    non_empty_tables: tuple[str, ...]
    non_seed_user_count: int

    @property
    def has_business_data(self) -> bool:
        return bool(self.non_empty_tables or self.non_seed_user_count)


@dataclass(frozen=True)
class FullRestoreEmptinessCheck:
    non_empty_tables: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.non_empty_tables


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
    table_sql = ", ".join(quote_table(table) for table in reversed(CORE_BACKUP_TABLES))
    with connection.cursor() as cursor:
        cursor.execute(f"TRUNCATE TABLE {table_sql} RESTART IDENTITY CASCADE")


def sequence_columns_for_table(table: str) -> tuple[str, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, column_default, identity_generation
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            [table],
        )
        rows = cursor.fetchall()
    all_columns = [row[0] for row in rows]
    columns = [
        column_name
        for column_name, column_default, identity_generation in rows
        if (column_default or "").startswith("nextval(") or identity_generation is not None
    ]
    if "id" in all_columns and "id" not in columns:
        columns.insert(0, "id")
    return tuple(columns)


def reseed_table_sequences(tables: Iterable[str]) -> None:
    with connection.cursor() as cursor:
        for table in tables:
            quoted_table = quote_table(table)
            for column in sequence_columns_for_table(table):
                cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [f"public.{table}", column])
                row = cursor.fetchone()
                sequence_name = row[0] if row else None
                if not sequence_name:
                    continue
                quoted_column = quote_table(column)
                cursor.execute(
                    f"""
                    SELECT setval(
                        %s,
                        COALESCE(MAX({quoted_column}), 1),
                        MAX({quoted_column}) IS NOT NULL
                    )
                    FROM {quoted_table}
                    """,
                    [sequence_name],
                )


def reseed_core_sequences() -> None:
    reseed_table_sequences(CORE_BACKUP_TABLES)


def user_tables_for_full_restore_check() -> tuple[str, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = 'public'
              AND tablename <> 'django_migrations'
            ORDER BY tablename
            """
        )
        return tuple(row[0] for row in cursor.fetchall())


def check_database_empty_for_full_restore() -> FullRestoreEmptinessCheck:
    non_empty = tuple(table for table in user_tables_for_full_restore_check() if table_count(table))
    return FullRestoreEmptinessCheck(non_empty_tables=non_empty)


def expire_pending_invitations_after_restore() -> int:
    with transaction.atomic():
        restored_at = timezone.now()
        return (
            Invitation.objects.select_for_update()
            .filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=restored_at),
                is_claimed=False,
                revoked_at__isnull=True,
            )
            .update(expires_at=restored_at)
        )


def validate_core_restore() -> list[str]:
    errors: list[str] = []

    duplicate_emails = (
        User.objects.values("email").order_by().annotate(count=Count("id")).filter(count__gt=1)
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
