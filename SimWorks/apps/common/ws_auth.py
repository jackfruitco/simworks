"""WebSocket authentication helpers.

Supports session-authenticated web clients and JWT-authenticated mobile clients.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from api.v1.auth import InvalidTokenError, decode_access_token

logger = logging.getLogger(__name__)
User = get_user_model()


@database_sync_to_async
def _get_user_for_token_subject(subject: str):
    user = User.objects.filter(pk=subject, is_active=True).first()
    return user or AnonymousUser()


def _extract_bearer_token(scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() != b"authorization":
            continue
        try:
            raw = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if raw.lower().startswith("bearer "):
            return raw.split(" ", 1)[1].strip()

    query = parse_qs(scope.get("query_string", b"").decode("utf-8"))
    token = query.get("token", [None])[0]
    return token.strip() if isinstance(token, str) else None


class JWTAuthMiddleware(BaseMiddleware):
    """Populate scope.user from JWT when session auth is unavailable."""

    async def __call__(self, scope, receive, send):
        user = scope.get("user")
        if user is not None and getattr(user, "is_authenticated", False):
            return await super().__call__(scope, receive, send)

        token = _extract_bearer_token(scope)
        if token:
            try:
                payload = decode_access_token(token)
                subject = payload.get("sub")
                if subject:
                    scope["user"] = await _get_user_for_token_subject(subject)
            except InvalidTokenError as exc:
                logger.debug("websocket.jwt_auth_failed: %s", exc)
            except Exception:
                logger.exception("websocket.jwt_auth_unexpected_error")

        if scope.get("user") is None:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def SessionOrJWTAuthMiddlewareStack(inner):
    """Auth stack supporting Django sessions and JWT bearer tokens."""
    return AuthMiddlewareStack(JWTAuthMiddleware(inner))
