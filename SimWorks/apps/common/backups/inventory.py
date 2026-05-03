"""Explicit table inventory for PostgreSQL logical backups."""

from __future__ import annotations

from dataclasses import dataclass

CORE_BACKUP_TABLES: tuple[str, ...] = (
    "django_content_type",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "django_site",
    "accounts_user",
    "accounts_user_groups",
    "accounts_user_user_permissions",
    "accounts_userrole",
    "accounts_roleresource",
    "account_emailaddress",
    "account_emailconfirmation",
    "socialaccount_socialapp",
    "socialaccount_socialaccount",
    "socialaccount_socialtoken",
    "accounts_account",
    "accounts_accountmembership",
    "accounts_lab",
    "accounts_labmembership",
    "accounts_invitation",
    "billing_billingaccount",
    "billing_subscription",
    "billing_entitlement",
    "billing_seatallocation",
    "billing_seatassignment",
)

CORE_BUSINESS_TABLES: tuple[str, ...] = (
    "auth_group",
    "auth_group_permissions",
    "accounts_user",
    "accounts_user_groups",
    "accounts_user_user_permissions",
    "accounts_userrole",
    "accounts_roleresource",
    "account_emailaddress",
    "account_emailconfirmation",
    "socialaccount_socialapp",
    "socialaccount_socialaccount",
    "socialaccount_socialtoken",
    "accounts_account",
    "accounts_accountmembership",
    "accounts_lab",
    "accounts_labmembership",
    "accounts_invitation",
    "billing_billingaccount",
    "billing_subscription",
    "billing_entitlement",
    "billing_seatallocation",
    "billing_seatassignment",
)

CORE_FORBIDDEN_TABLES: tuple[str, ...] = (
    "django_session",
    "accounts_accountauditevent",
    "accounts_invitationauditevent",
    "billing_webhookevent",
    "chatlab_message",
    "simcore_simulation",
    "simcore_simulationimage",
    "trainerlab_runtimeevent",
    "service_call",
    "service_call_attempt",
    "common_outboxevent",
)

BACKUP_MODES = ("core", "full")
BACKUP_ADVISORY_LOCK_ID = 714_202_605_030_001


@dataclass(frozen=True)
class BackupInventory:
    mode: str
    tables: tuple[str, ...]


def inventory_for_mode(mode: str) -> BackupInventory:
    if mode == "core":
        return BackupInventory(mode=mode, tables=CORE_BACKUP_TABLES)
    if mode == "full":
        return BackupInventory(mode=mode, tables=())
    raise ValueError(f"Unsupported backup mode: {mode}")


def assert_core_inventory_safe() -> None:
    forbidden = set(CORE_FORBIDDEN_TABLES).intersection(CORE_BACKUP_TABLES)
    if forbidden:
        table_list = ", ".join(sorted(forbidden))
        raise ValueError(f"Core backup allowlist contains forbidden tables: {table_list}")
