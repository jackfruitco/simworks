from __future__ import annotations

from apps.accounts.models import Account, AccountMembership


def get_account_membership(user, account) -> AccountMembership | None:
    if not getattr(user, "is_authenticated", False):
        return None
    if account.owner_user_id == user.id and account.account_type == Account.AccountType.PERSONAL:
        return AccountMembership(
            account=account,
            user=user,
            invite_email=user.email or "",
            role=AccountMembership.Role.ORG_ADMIN,
            status=AccountMembership.Status.ACTIVE,
        )
    return (
        AccountMembership.objects.filter(
            account=account,
            user=user,
            status=AccountMembership.Status.ACTIVE,
            ended_at__isnull=True,
        )
        .select_related("account")
        .first()
    )


def can_access_account(user, account) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if account.owner_user_id == user.id and account.account_type == Account.AccountType.PERSONAL:
        return True
    return get_account_membership(user, account) is not None


def can_manage_billing(user, account) -> bool:
    if user.is_superuser:
        return True
    membership = get_account_membership(user, account)
    if membership is None:
        return False
    if account.account_type == Account.AccountType.PERSONAL:
        return account.owner_user_id == user.id
    return membership.role in {
        AccountMembership.Role.ORG_ADMIN,
        AccountMembership.Role.BILLING_ADMIN,
    }


def can_manage_members(user, account) -> bool:
    if user.is_superuser:
        return True
    membership = get_account_membership(user, account)
    if membership is None:
        return False
    if account.account_type == Account.AccountType.PERSONAL:
        return account.owner_user_id == user.id
    return membership.role == AccountMembership.Role.ORG_ADMIN


def can_view_account_runs(user, account) -> bool:
    if user.is_superuser:
        return True
    membership = get_account_membership(user, account)
    if membership is None:
        return False
    if account.account_type == Account.AccountType.PERSONAL:
        return account.owner_user_id == user.id
    return membership.role in {
        AccountMembership.Role.ORG_ADMIN,
        AccountMembership.Role.INSTRUCTOR,
    }


def can_assign_instructors(user, account) -> bool:
    return can_manage_members(user, account)


def can_view_simulation(user, simulation) -> bool:
    account = getattr(simulation, "account", None)
    if account is None:
        return simulation.user_id == getattr(user, "id", None)
    if not can_access_account(user, account):
        return False
    if can_view_account_runs(user, account):
        return True
    return simulation.user_id == getattr(user, "id", None)


def can_export_simulation(user, account, simulation) -> bool:
    if getattr(simulation, "account_id", None) != getattr(account, "id", None):
        return False
    return can_view_simulation(user, simulation)
