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
    user = User.objects.filter(pk=subject, is_active=True).first()
    return user or AnonymousUser()


def _extract_bearer_token(scope) -> str | None:
    """Extract bearer token from the Authorization header only.

    Query-parameter tokens are no longer supported. Clients must use the
    ``Authorization: Bearer <token>`` header for WebSocket authentication.
    """
    for key, value in scope.get("headers", []):
        if key.lower() != b"authorization":
            continue
        try:
            raw = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if raw.lower().startswith("bearer "):
            return raw.split(" ", 1)[1].strip()
    return None


class JWTAuthMiddleware(BaseMiddleware):
    """Populate ``scope["user"]`` from JWT when session auth is unavailable."""

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        user = scope.get("user")
        has_session_user = user is not None and getattr(user, "is_authenticated", False)

        if has_session_user:
            logger.debug(
                "ws.auth.session_user_present",
                path=path,
                user_id=getattr(user, "id", None),
                auth_mechanism="session",
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
                        )
                    else:
                        logger.warning(
                            "ws.auth.jwt_user_inactive",
                            path=path,
                        )
            except InvalidTokenError as exc:
                logger.warning(
                    "ws.auth.jwt_failed",
                    path=path,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            except Exception:
                logger.exception("ws.auth.jwt_unexpected_error", path=path)

        if scope.get("user") is None:
            scope["user"] = AnonymousUser()

        if not getattr(scope["user"], "is_authenticated", False):
            scope["auth_mechanism"] = None
            logger.debug(
                "ws.auth.anonymous_fallback",
                path=path,
                had_bearer_token=has_bearer_token,
            )

        return await super().__call__(scope, receive, send)


@database_sync_to_async
def _resolve_account_from_scope(scope, user):
    from apps.accounts.context import resolve_scope_account

    return resolve_scope_account(scope, user)


class AccountContextMiddleware(BaseMiddleware):
    """Resolve account context from ``X-Account-UUID`` header into ``scope["account"]``.

    Runs after auth middleware so ``scope["user"]`` is already populated.
    Sets ``scope["account"]`` to the resolved :class:`Account` instance or ``None``.
    """

    async def __call__(self, scope, receive, send):
        user = scope.get("user")
        path = scope.get("path", "")
        is_authenticated = user is not None and getattr(user, "is_authenticated", False)

        if not is_authenticated:
            scope["account"] = None
            scope["account_context_source"] = None
            logger.debug(
                "ws.account.skip_anonymous",
                path=path,
            )
            return await super().__call__(scope, receive, send)

        # Check for X-Account-UUID header presence
        from apps.accounts.context import get_requested_account_uuid_from_scope

        requested_uuid = get_requested_account_uuid_from_scope(scope)
        has_account_header = requested_uuid is not None

        account = await _resolve_account_from_scope(scope, user)
        account_id = getattr(account, "id", None)
        account_uuid = str(getattr(account, "uuid", "")) if account else None

        scope["account"] = account
        scope["account_context_source"] = "header" if has_account_header else "default"

        logger.info(
            "ws.account.resolved",
            path=path,
            user_id=getattr(user, "id", None),
            account_id=account_id,
            account_uuid=account_uuid,
            account_context_source=scope["account_context_source"],
            has_account_header=has_account_header,
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
