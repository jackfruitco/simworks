"""Tests for WebSocket authentication middleware.

Covers:
- _extract_bearer_token: Authorization header and query param extraction
- JWTAuthMiddleware: sets scope["user"] from valid JWT, falls back to AnonymousUser
- SessionOrJWTAuthMiddlewareStack ordering: session auth runs first so JWT is
  not overwritten (regression test for the iOS 403 bug)
- End-to-end WS connection through the full ASGI app using JWT
"""

from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode
from uuid import uuid4

from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
import pytest

from api.v1.auth import create_access_token
from apps.common.ws_auth import (
    JWTAuthMiddleware,
    SessionOrJWTAuthMiddlewareStack,
    _extract_bearer_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope(headers=None, query_string=b""):
    """Build a minimal ASGI websocket scope."""
    return {
        "type": "websocket",
        "headers": headers or [],
        "query_string": query_string,
    }


def _header(name: str, value: str):
    return (name.encode(), value.encode())


# ---------------------------------------------------------------------------
# _extract_bearer_token
# ---------------------------------------------------------------------------


class TestExtractBearerToken:
    """Unit tests for the token extraction helper."""

    def test_extracts_token_from_authorization_header(self):
        scope = _make_scope(headers=[_header("authorization", "Bearer mytoken123")])
        assert _extract_bearer_token(scope) == "mytoken123"

    def test_header_matching_is_case_insensitive(self):
        scope = _make_scope(headers=[_header("Authorization", "Bearer MyToken")])
        assert _extract_bearer_token(scope) == "MyToken"

    def test_extracts_token_from_query_param(self):
        qs = urlencode({"token": "querytoken456"}).encode()
        scope = _make_scope(query_string=qs)
        assert _extract_bearer_token(scope) == "querytoken456"

    def test_header_takes_priority_over_query_param(self):
        qs = urlencode({"token": "querytoken"}).encode()
        scope = _make_scope(
            headers=[_header("authorization", "Bearer headertoken")],
            query_string=qs,
        )
        assert _extract_bearer_token(scope) == "headertoken"

    def test_returns_none_when_no_token_present(self):
        scope = _make_scope()
        assert _extract_bearer_token(scope) is None

    def test_returns_none_for_non_bearer_authorization_header(self):
        scope = _make_scope(headers=[_header("authorization", "Basic dXNlcjpwYXNz")])
        assert _extract_bearer_token(scope) is None

    def test_strips_whitespace_from_token(self):
        scope = _make_scope(headers=[_header("authorization", "Bearer  spaced  ")])
        assert _extract_bearer_token(scope) == "spaced"


# ---------------------------------------------------------------------------
# JWTAuthMiddleware (unit)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestJWTAuthMiddleware:
    """Unit tests for JWTAuthMiddleware scope population."""

    async def _call_middleware(self, scope):
        """Run JWTAuthMiddleware and return the scope it passed to the inner app."""
        captured = {}

        async def inner(s, receive, send):
            captured["scope"] = s

        middleware = JWTAuthMiddleware(inner)
        await middleware(scope, AsyncMock(), AsyncMock())
        return captured.get("scope", scope)

    async def test_sets_user_from_valid_jwt_in_header(self):
        from apps.accounts.models import UserRole

        role, _ = await UserRole.objects.aget_or_create(title="WS JWT Test")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = await User.objects.acreate(email=f"ws_jwt_{uuid4().hex[:6]}@test.com", role=role)
        token = create_access_token(user)

        scope = _make_scope(headers=[_header("authorization", f"Bearer {token}")])
        result = await self._call_middleware(scope)

        assert result["user"].pk == user.pk
        assert result["user"].is_authenticated

    async def test_sets_user_from_valid_jwt_in_query_param(self):
        from apps.accounts.models import UserRole

        role, _ = await UserRole.objects.aget_or_create(title="WS JWT QP Test")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = await User.objects.acreate(email=f"ws_jwt_qp_{uuid4().hex[:6]}@test.com", role=role)
        token = create_access_token(user)

        qs = urlencode({"token": token}).encode()
        scope = _make_scope(query_string=qs)
        result = await self._call_middleware(scope)

        assert result["user"].pk == user.pk
        assert result["user"].is_authenticated

    async def test_falls_back_to_anonymous_when_no_token(self):
        scope = _make_scope()
        result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)

    async def test_falls_back_to_anonymous_for_invalid_token(self):
        scope = _make_scope(headers=[_header("authorization", "Bearer not.a.valid.jwt")])
        result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)

    async def test_skips_jwt_when_user_already_authenticated(self):
        """If session auth already populated scope['user'], JWT is not attempted."""
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole

        User = get_user_model()
        role, _ = await UserRole.objects.aget_or_create(title="WS Session Test")
        session_user = await User.objects.acreate(
            email=f"ws_session_{uuid4().hex[:6]}@test.com", role=role
        )

        # Pre-populate scope as if session middleware already ran
        scope = _make_scope(headers=[_header("authorization", "Bearer ignored")])
        scope["user"] = session_user

        result = await self._call_middleware(scope)

        # User must be the session user, not resolved from the (ignored) token
        assert result["user"].pk == session_user.pk

    async def test_falls_back_to_anonymous_for_inactive_user(self):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole

        User = get_user_model()
        role, _ = await UserRole.objects.aget_or_create(title="WS Inactive Test")
        user = await User.objects.acreate(
            email=f"ws_inactive_{uuid4().hex[:6]}@test.com",
            role=role,
            is_active=False,
        )
        token = create_access_token(user)

        scope = _make_scope(headers=[_header("authorization", f"Bearer {token}")])
        result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)


# ---------------------------------------------------------------------------
# Middleware stack ordering (regression test for the iOS 403 bug)
# ---------------------------------------------------------------------------


class TestSessionOrJWTAuthMiddlewareStackOrdering:
    """Verify that AuthMiddlewareStack wraps JWTAuthMiddleware, not vice-versa.

    Before the fix, the order was JWTAuthMiddleware(AuthMiddlewareStack(inner)),
    which caused AuthMiddlewareStack to overwrite the JWT-authenticated user with
    AnonymousUser when no session cookie was present (iOS clients).

    Correct order: AuthMiddlewareStack(JWTAuthMiddleware(inner)) — session auth
    runs first; JWT fills in for clients with no session.
    """

    def test_jwt_middleware_is_outermost_layer_of_inner_stack(self):
        """SessionOrJWTAuthMiddlewareStack must place JWTAuthMiddleware inside
        AuthMiddlewareStack so session auth cannot overwrite a JWT-resolved user."""
        inner = MagicMock()
        stack = SessionOrJWTAuthMiddlewareStack(inner)

        # The outermost layer should be AuthMiddlewareStack (or its wrapper),
        # NOT JWTAuthMiddleware.  We verify this by checking that the *inner*
        # of the outermost layer is a JWTAuthMiddleware instance.
        #
        # channels' AuthMiddlewareStack wraps inner in SessionMiddleware then
        # AuthMiddleware, so we walk the chain looking for JWTAuthMiddleware.

        def find_jwt_depth(obj, depth=0):
            """Return (depth, found) walking .inner attributes."""
            if isinstance(obj, JWTAuthMiddleware):
                return depth, True
            inner_app = getattr(obj, "inner", None)
            if inner_app is None or inner_app is obj:
                return depth, False
            return find_jwt_depth(inner_app, depth + 1)

        depth, found = find_jwt_depth(stack)
        assert found, "JWTAuthMiddleware not found in middleware stack"
        assert depth > 0, (
            "JWTAuthMiddleware must not be the outermost layer — "
            "it should be wrapped by AuthMiddlewareStack so session auth runs first"
        )


# ---------------------------------------------------------------------------
# End-to-end: JWT WebSocket connection through the full ASGI app
# ---------------------------------------------------------------------------


def _make_ws_app():
    """Build the auth+routing stack without AllowedHostsOriginValidator.

    The full ASGI app wraps the websocket handler in AllowedHostsOriginValidator,
    which rejects connections without a matching Origin header. For auth tests we
    want to exercise SessionOrJWTAuthMiddlewareStack in isolation, so we build the
    same stack (auth middleware + URL router) directly.
    """
    from channels.routing import URLRouter

    from apps.chatlab.routing import websocket_urlpatterns as chatlab_ws
    from apps.common.routing import websocket_urlpatterns as core_ws
    from apps.common.ws_auth import SessionOrJWTAuthMiddlewareStack

    return SessionOrJWTAuthMiddlewareStack(URLRouter(chatlab_ws + core_ws))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestJWTWebSocketEndToEnd:
    """Integration tests: iOS-style JWT auth through SessionOrJWTAuthMiddlewareStack.

    Uses the auth+routing stack directly (without AllowedHostsOriginValidator) so
    tests focus on authentication rather than origin validation.
    """

    async def _make_user_and_simulation(self):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole
        from apps.simcore.models import Simulation

        User = get_user_model()
        role, _ = await UserRole.objects.aget_or_create(title="WS E2E Test")
        user = await User.objects.acreate(email=f"ws_e2e_{uuid4().hex[:6]}@test.com", role=role)
        simulation = await Simulation.objects.acreate(
            user=user,
            sim_patient_full_name="E2E Patient",
        )
        return user, simulation

    async def test_jwt_in_header_allows_ws_connection(self):
        """Mobile client with Authorization: Bearer <token> can connect."""
        user, simulation = await self._make_user_and_simulation()
        token = create_access_token(user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/simulation/{simulation.id}/",
            headers=[(b"authorization", f"Bearer {token}".encode())],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        response = await communicator.receive_json_from()
        assert response["type"] == "init_message"

        await communicator.disconnect()

    async def test_jwt_in_query_param_allows_ws_connection(self):
        """Mobile client with ?token=<jwt> can connect."""
        user, simulation = await self._make_user_and_simulation()
        token = create_access_token(user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/simulation/{simulation.id}/?token={token}",
        )
        connected, _ = await communicator.connect()
        assert connected is True

        response = await communicator.receive_json_from()
        assert response["type"] == "init_message"

        await communicator.disconnect()

    async def test_no_auth_rejects_ws_connection(self):
        """WS connection without any auth is rejected (close code 4403)."""
        _, simulation = await self._make_user_and_simulation()

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/simulation/{simulation.id}/",
        )
        connected, _ = await communicator.connect()
        # Consumer accepts then immediately closes with 4403 for unauthenticated users
        assert connected is True

        response = await communicator.receive_json_from()
        assert response["type"] == "error"
        assert "access" in response["message"].lower()

        await communicator.disconnect()

    async def test_invalid_jwt_rejects_ws_connection(self):
        """WS connection with a malformed JWT is treated as unauthenticated."""
        _, simulation = await self._make_user_and_simulation()

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/simulation/{simulation.id}/",
            headers=[(b"authorization", b"Bearer not.a.real.token")],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        response = await communicator.receive_json_from()
        assert response["type"] == "error"

        await communicator.disconnect()

    async def test_jwt_user_cannot_access_other_users_simulation(self):
        """JWT-authenticated user is rejected for a simulation they don't own."""
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole

        User = get_user_model()
        role, _ = await UserRole.objects.aget_or_create(title="WS E2E Other")
        other_user = await User.objects.acreate(
            email=f"ws_other_{uuid4().hex[:6]}@test.com", role=role
        )

        _, simulation = await self._make_user_and_simulation()
        token = create_access_token(other_user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/simulation/{simulation.id}/",
            headers=[(b"authorization", f"Bearer {token}".encode())],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        response = await communicator.receive_json_from()
        assert response["type"] == "error"
        assert "access" in response["message"].lower()

        await communicator.disconnect()
