from __future__ import annotations

from urllib.parse import parse_qs
from uuid import UUID

from apps.accounts.models import Account
from apps.accounts.permissions import can_access_account
from apps.accounts.services import get_default_account_for_user

ACCOUNT_HEADER_NAME = "X-Account-UUID"


def _header_value(headers, name: str) -> str | None:
    wanted = name.lower().encode("utf-8")
    for key, value in headers or []:
        if key.lower() != wanted:
            continue
        try:
            return value.decode("utf-8").strip()
        except UnicodeDecodeError:
            return None
    return None


def get_requested_account_uuid_from_request(request) -> str | None:
    return request.headers.get(ACCOUNT_HEADER_NAME, "").strip() or None


def get_requested_account_uuid_from_scope(scope) -> str | None:
    header_value = _header_value(scope.get("headers", []), ACCOUNT_HEADER_NAME)
    if header_value:
        return header_value
    query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
    return (query.get("account_uuid") or [None])[0]


def resolve_account_for_user(user, *, account_uuid: str | None = None):
    if not getattr(user, "is_authenticated", False):
        return None

    account = None
    if account_uuid:
        try:
            parsed_account_uuid = UUID(str(account_uuid))
        except (TypeError, ValueError):
            return None
        account = Account.objects.filter(uuid=parsed_account_uuid, is_active=True).first()
        if account is None:
            return None
    else:
        account = get_default_account_for_user(user)

    if account is None:
        return None
    if not can_access_account(user, account):
        return None
    return account


def resolve_request_account(request, user=None):
    user = user or getattr(request, "auth", None) or getattr(request, "user", None)
    return resolve_account_for_user(
        user,
        account_uuid=get_requested_account_uuid_from_request(request),
    )


def resolve_scope_account(scope, user):
    return resolve_account_for_user(
        user,
        account_uuid=get_requested_account_uuid_from_scope(scope),
    )
