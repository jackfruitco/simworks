"""WebSocket authentication helpers.

Supports session-authenticated web clients and JWT-authenticated mobile clients.
Account context is normalized via ``X-Account-UUID`` header before consumers run.
"""

from __future__ import annotations

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from api.v1.auth import InvalidTokenError, decode_access_token
from config.logging import get_logger

logger = get_logger(__name__)
User = get_user_model()


@database_sync_to_async
def _get_user_for_token_subject(subject: str):
    try:
        subject_pk = int(subject)
    except (TypeError, ValueError):
        return AnonymousUser()

    user = User.objects.filter(pk=subject_pk, is_active=True).first()
    return user or AnonymousUser()


def _header_names(scope) -> list[str]:
    names: list[str] = []
    for key, _value in scope.get("headers", []):
        try:
            names.append(key.decode("utf-8").lower())
        except UnicodeDecodeError:
            names.append(repr(key))
    return sorted(names)


def _header_value(scope, name: str) -> str | None:
    target = name.lower().encode("utf-8")
    for key, value in scope.get("headers", []):
        if key.lower() != target:
            continue
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return repr(value)
    return None


def _request_context(scope) -> dict[str, str | None]:
    return {
        "host": _header_value(scope, "host"),
        "origin": _header_value(scope, "origin"),
        "user_agent": _header_value(scope, "user-agent"),
        "upgrade": _header_value(scope, "upgrade"),
        "connection": _header_value(scope, "connection"),
        "sec_websocket_version": _header_value(scope, "sec-websocket-version"),
        "sec_websocket_protocol": _header_value(scope, "sec-websocket-protocol"),
        "x_forwarded_for": _header_value(scope, "x-forwarded-for"),
        "x_forwarded_proto": _header_value(scope, "x-forwarded-proto"),
        "x_forwarded_host": _header_value(scope, "x-forwarded-host"),
        "x_forwarded_port": _header_value(scope, "x-forwarded-port"),
        "x_account_uuid": _header_value(scope, "x-account-uuid"),
        "x_correlation_id": _header_value(scope, "x-correlation-id"),
    }


def _has_header(scope, name: str) -> bool:
    target = name.lower().encode("utf-8")
    return any(key.lower() == target for key, _value in scope.get("headers", []))


def _extract_bearer_token(scope) -> str | None:
    """Extract bearer token from the Authorization header only.

    Query-parameter tokens are no longer supported. Clients must use the
    ``Authorization: Bearer <token>`` header for WebSocket authentication.
    """
    headers = scope.get("headers", [])
    path = scope.get("path", "")
    header_names = _header_names(scope)
    request_context = _request_context(scope)

    for key, value in headers:
        if key.lower() != b"authorization":
            continue
        try:
            raw = value.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning(
                "ws.auth.authorization_header_invalid_encoding",
                path=path,
                header_names=header_names,
                **request_context,
            )
            return None
        if raw.lower().startswith("bearer "):
            logger.debug(
                "ws.auth.authorization_header_present",
                path=path,
                header_names=header_names,
                **request_context,
            )
            return raw.split(" ", 1)[1].strip()
        logger.warning(
            "ws.auth.authorization_header_unexpected_format",
            path=path,
            header_names=header_names,
            **request_context,
        )
        return None

    logger.debug(
        "ws.auth.authorization_header_missing",
        path=path,
        header_names=header_names,
        **request_context,
    )
    return None


class JWTAuthMiddleware(BaseMiddleware):
    """Populate ``scope["user"]`` from JWT when session auth is unavailable."""

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        user = scope.get("user")
        has_session_user = user is not None and getattr(user, "is_authenticated", False)
        request_context = _request_context(scope)
        header_names = _header_names(scope)
        has_account_header = _has_header(scope, "x-account-uuid")

        if has_session_user:
            logger.debug(
                "ws.auth.session_user_present",
                path=path,
                user_id=getattr(user, "id", None),
                auth_mechanism="session",
                **request_context,
            )
            scope["auth_mechanism"] = "session"
            return await super().__call__(scope, receive, send)

        token = _extract_bearer_token(scope)
        has_bearer_token = token is not None

        logger.debug(
            "ws.auth.start",
            path=path,
            has_session_user=False,
            has_bearer_token=has_bearer_token,
            header_names=header_names,
            has_account_header=has_account_header,
            **request_context,
        )

        if token:
            try:
                payload = decode_access_token(token)
                subject = payload.get("sub")
                if subject:
                    scope["user"] = await _get_user_for_token_subject(subject)
                    if getattr(scope["user"], "is_authenticated", False):
                        scope["auth_mechanism"] = "bearer_token"
                        logger.info(
                            "ws.auth.jwt_success",
                            path=path,
                            user_id=scope["user"].pk,
                            auth_mechanism="bearer_token",
                            **request_context,
                        )
                    else:
                        logger.warning(
                            "ws.auth.jwt_user_not_found_or_inactive",
                            path=path,
                            **request_context,
                        )
            except InvalidTokenError as exc:
                logger.warning(
                    "ws.auth.jwt_failed",
                    path=path,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    header_names=header_names,
                    has_account_header=has_account_header,
                    **request_context,
                )
            except Exception:
                logger.exception(
                    "ws.auth.jwt_unexpected_error",
                    path=path,
                    **request_context,
                )

        if scope.get("user") is None:
            scope["user"] = AnonymousUser()

        if not getattr(scope["user"], "is_authenticated", False):
            scope["auth_mechanism"] = None
            fallback_reason = (
                "invalid_or_inactive_bearer_token" if has_bearer_token else "missing_bearer_token"
            )
            log_anonymous_fallback = logger.warning if has_bearer_token else logger.debug
            log_anonymous_fallback(
                "ws.auth.anonymous_fallback",
                path=path,
                had_bearer_token=has_bearer_token,
                reason=fallback_reason,
                header_names=header_names,
                has_account_header=has_account_header,
                **request_context,
            )

        return await super().__call__(scope, receive, send)


@database_sync_to_async
def _resolve_account_from_scope(scope, user):
    from apps.accounts.context import (
        get_requested_account_uuid_from_scope,
        resolve_account_for_user_with_reason,
    )

    requested_uuid = get_requested_account_uuid_from_scope(scope)
    account, resolution_reason = resolve_account_for_user_with_reason(
        user,
        account_uuid=requested_uuid,
    )
    return account, requested_uuid, resolution_reason


class AccountContextMiddleware(BaseMiddleware):
    """Resolve account context from ``X-Account-UUID`` header into ``scope["account"]``.

    Runs after auth middleware so ``scope["user"]`` is already populated.
    Sets ``scope["account"]`` to the resolved :class:`Account` instance or ``None``.
    """

    async def __call__(self, scope, receive, send):
        user = scope.get("user")
        path = scope.get("path", "")
        is_authenticated = user is not None and getattr(user, "is_authenticated", False)
        request_context = _request_context(scope)

        if not is_authenticated:
            scope["account"] = None
            scope["account_context_source"] = None
            logger.debug(
                "ws.account.skip_anonymous",
                path=path,
                reason="anonymous_user",
                **request_context,
            )
            return await super().__call__(scope, receive, send)

        account, requested_uuid, resolution_reason = await _resolve_account_from_scope(scope, user)
        has_account_header = requested_uuid is not None
        account_id = getattr(account, "id", None)
        account_uuid = str(getattr(account, "uuid", "")) if account else None

        scope["account"] = account
        scope["account_context_source"] = "header" if has_account_header else "default"
        log = logger.info
        event_name = "ws.account.resolved"
        if has_account_header and account is None:
            log = logger.warning
            event_name = "ws.account.resolution_failed"

        log(
            event_name,
            path=path,
            user_id=getattr(user, "id", None),
            account_id=account_id,
            account_uuid=account_uuid,
            requested_account_uuid=requested_uuid,
            account_context_source=scope["account_context_source"],
            has_account_header=has_account_header,
            reason=resolution_reason,
            **request_context,
        )

        return await super().__call__(scope, receive, send)


def SessionOrJWTAuthMiddlewareStack(inner):
    """Auth stack supporting Django sessions, JWT bearer tokens, and account context.

    Middleware order (outermost to innermost):
      1. AuthMiddlewareStack — session auth
      2. JWTAuthMiddleware — JWT bearer token fallback
      3. AccountContextMiddleware — resolve account from X-Account-UUID header
    """
    return AuthMiddlewareStack(JWTAuthMiddleware(AccountContextMiddleware(inner)))
