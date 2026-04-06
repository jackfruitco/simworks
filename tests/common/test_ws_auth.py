"""Tests for WebSocket authentication and account context middleware.

Covers:
- _extract_bearer_token: Authorization header extraction (query params removed)
- JWTAuthMiddleware: sets scope["user"] from valid JWT, falls back to AnonymousUser
- AccountContextMiddleware: resolves scope["account"] from X-Account-UUID header
- SessionOrJWTAuthMiddlewareStack ordering: session auth runs first so JWT is
  not overwritten (regression test for the iOS 403 bug)
- End-to-end WS connection through the full ASGI app using JWT + account headers
- Query-param auth/account selection is no longer supported
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
import pytest

from api.v1.auth import create_access_token
from apps.common.ws_auth import (
    AccountContextMiddleware,
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

    def test_returns_none_when_no_token_present(self):
        scope = _make_scope()
        assert _extract_bearer_token(scope) is None

    def test_returns_none_for_non_bearer_authorization_header(self):
        scope = _make_scope(headers=[_header("authorization", "Basic dXNlcjpwYXNz")])
        assert _extract_bearer_token(scope) is None

    def test_strips_whitespace_from_token(self):
        scope = _make_scope(headers=[_header("authorization", "Bearer  spaced  ")])
        assert _extract_bearer_token(scope) == "spaced"

    def test_query_param_token_is_ignored(self):
        """Query-param tokens are no longer supported."""
        from urllib.parse import urlencode

        qs = urlencode({"token": "querytoken456"}).encode()
        scope = _make_scope(query_string=qs)
        assert _extract_bearer_token(scope) is None

    def test_query_param_token_ignored_even_without_header(self):
        """Ensure no fallback to query params when header is absent."""
        from urllib.parse import urlencode

        qs = urlencode({"token": "should_be_ignored"}).encode()
        scope = _make_scope(query_string=qs)
        assert _extract_bearer_token(scope) is None


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
        assert result["auth_mechanism"] == "bearer_token"

    async def test_falls_back_to_anonymous_when_no_token(self):
        scope = _make_scope()
        result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)
        assert result["auth_mechanism"] is None

    async def test_missing_bearer_token_logs_explicit_reason(self):
        scope = _make_scope()

        with patch("apps.common.ws_auth.logger.debug") as mock_debug:
            result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)
        fallback_call = next(
            call
            for call in mock_debug.call_args_list
            if call.args[0] == "ws.auth.anonymous_fallback"
        )
        assert fallback_call.kwargs["had_bearer_token"] is False
        assert fallback_call.kwargs["reason"] == "missing_bearer_token"

    async def test_falls_back_to_anonymous_for_invalid_token(self):
        scope = _make_scope(headers=[_header("authorization", "Bearer not.a.valid.jwt")])
        result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)
        assert result["auth_mechanism"] is None

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
        assert result["auth_mechanism"] == "session"

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

    async def test_query_param_jwt_is_not_accepted(self):
        """Query-param JWT tokens are no longer supported for auth."""
        from urllib.parse import urlencode

        from apps.accounts.models import UserRole

        role, _ = await UserRole.objects.aget_or_create(title="WS QP Reject")
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = await User.objects.acreate(
            email=f"ws_qp_reject_{uuid4().hex[:6]}@test.com", role=role
        )
        token = create_access_token(user)

        qs = urlencode({"token": token}).encode()
        scope = _make_scope(query_string=qs)
        result = await self._call_middleware(scope)

        assert isinstance(result["user"], AnonymousUser)


# ---------------------------------------------------------------------------
# AccountContextMiddleware (unit)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestAccountContextMiddleware:
    """Unit tests for AccountContextMiddleware scope population."""

    async def _call_middleware(self, scope):
        """Run AccountContextMiddleware and return the scope it passed to the inner app."""
        captured = {}

        async def inner(s, receive, send):
            captured["scope"] = s

        middleware = AccountContextMiddleware(inner)
        await middleware(scope, AsyncMock(), AsyncMock())
        return captured.get("scope", scope)

    async def _make_user_with_account(self):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole
        from apps.accounts.services import get_default_account_for_user

        User = get_user_model()
        role, _ = await UserRole.objects.aget_or_create(title="WS Account Test")
        user = await User.objects.acreate(email=f"ws_acct_{uuid4().hex[:6]}@test.com", role=role)
        from asgiref.sync import sync_to_async

        account = await sync_to_async(get_default_account_for_user)(user)
        return user, account

    async def test_sets_scope_account_from_header(self):
        user, account = await self._make_user_with_account()

        scope = _make_scope(
            headers=[_header("x-account-uuid", str(account.uuid))],
        )
        scope["user"] = user

        result = await self._call_middleware(scope)
        assert result["account"] is not None
        assert result["account"].id == account.id
        assert result["account_context_source"] == "header"

    async def test_scope_account_uses_default_without_header(self):
        user, account = await self._make_user_with_account()

        scope = _make_scope()
        scope["user"] = user

        result = await self._call_middleware(scope)
        # Without header, falls back to default account for user
        assert result["account"] is not None
        assert result["account"].id == account.id
        assert result["account_context_source"] == "default"

    async def test_default_account_resolution_logs_reason(self):
        user, account = await self._make_user_with_account()

        scope = _make_scope()
        scope["user"] = user

        with patch("apps.common.ws_auth.logger.info") as mock_info:
            result = await self._call_middleware(scope)

        assert result["account"] is not None
        assert result["account"].id == account.id
        resolved_call = next(
            call for call in mock_info.call_args_list if call.args[0] == "ws.account.resolved"
        )
        assert resolved_call.kwargs["reason"] == "default_account_resolved"
        assert resolved_call.kwargs["has_account_header"] is False
        assert resolved_call.kwargs["requested_account_uuid"] is None

    async def test_scope_account_is_none_for_anonymous(self):
        scope = _make_scope()
        scope["user"] = AnonymousUser()

        result = await self._call_middleware(scope)
        assert result["account"] is None
        assert result["account_context_source"] is None

    async def test_scope_account_is_none_for_invalid_uuid(self):
        user, _account = await self._make_user_with_account()

        scope = _make_scope(
            headers=[_header("x-account-uuid", "not-a-valid-uuid")],
        )
        scope["user"] = user

        with patch("apps.common.ws_auth.logger.warning") as mock_warning:
            result = await self._call_middleware(scope)

        assert result["account"] is None
        assert result["account_context_source"] == "header"
        warning_call = next(
            call
            for call in mock_warning.call_args_list
            if call.args[0] == "ws.account.resolution_failed"
        )
        assert warning_call.kwargs["reason"] == "invalid_account_uuid"
        assert warning_call.kwargs["requested_account_uuid"] == "not-a-valid-uuid"
        assert warning_call.kwargs["has_account_header"] is True

    async def test_scope_account_is_none_for_wrong_account(self):
        """Valid UUID but user has no access to that account."""
        user, _own_account = await self._make_user_with_account()

        # Create a different account the user does NOT have access to
        from apps.accounts.models import Account

        other_account = await Account.objects.acreate(
            name="Other Org",
            slug=f"other-org-{uuid4().hex[:6]}",
            account_type=Account.AccountType.ORGANIZATION,
        )

        scope = _make_scope(
            headers=[_header("x-account-uuid", str(other_account.uuid))],
        )
        scope["user"] = user

        with patch("apps.common.ws_auth.logger.warning") as mock_warning:
            result = await self._call_middleware(scope)

        assert result["account"] is None
        assert result["account_context_source"] == "header"
        warning_call = next(
            call
            for call in mock_warning.call_args_list
            if call.args[0] == "ws.account.resolution_failed"
        )
        assert warning_call.kwargs["reason"] == "account_access_denied"
        assert warning_call.kwargs["requested_account_uuid"] == str(other_account.uuid)
        assert warning_call.kwargs["has_account_header"] is True

    async def test_query_param_account_uuid_is_ignored(self):
        """Query-param account_uuid is no longer supported."""
        from urllib.parse import urlencode

        user, account = await self._make_user_with_account()

        qs = urlencode({"account_uuid": str(account.uuid)}).encode()
        scope = _make_scope(query_string=qs)
        scope["user"] = user

        result = await self._call_middleware(scope)
        # Should resolve default account, not the one in query param
        # (the query param is ignored, default account is returned)
        assert result["account"] is not None
        assert result["account_context_source"] == "default"


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

    def test_account_context_middleware_is_innermost(self):
        """AccountContextMiddleware should be the innermost middleware layer."""
        inner = MagicMock()
        stack = SessionOrJWTAuthMiddlewareStack(inner)

        def find_account_depth(obj, depth=0):
            if isinstance(obj, AccountContextMiddleware):
                return depth, True
            inner_app = getattr(obj, "inner", None)
            if inner_app is None or inner_app is obj:
                return depth, False
            return find_account_depth(inner_app, depth + 1)

        depth, found = find_account_depth(stack)
        assert found, "AccountContextMiddleware not found in middleware stack"

        # AccountContextMiddleware should be deeper than JWTAuthMiddleware
        def find_jwt_depth(obj, depth=0):
            if isinstance(obj, JWTAuthMiddleware):
                return depth, True
            inner_app = getattr(obj, "inner", None)
            if inner_app is None or inner_app is obj:
                return depth, False
            return find_jwt_depth(inner_app, depth + 1)

        jwt_depth, _ = find_jwt_depth(stack)
        assert depth > jwt_depth, (
            "AccountContextMiddleware must be inside JWTAuthMiddleware "
            "so that scope['user'] is resolved before account resolution"
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
            "/ws/v1/chatlab/",
            headers=[(b"authorization", f"Bearer {token}".encode())],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to(
            {
                "event_type": "session.hello",
                "payload": {"simulation_id": simulation.id},
            }
        )
        response = await communicator.receive_json_from()
        assert response["event_type"] == "session.ready"

        await communicator.disconnect()

    async def test_no_auth_rejects_ws_connection(self):
        """WS connection without any auth is rejected before accept."""
        await self._make_user_and_simulation()

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            "/ws/v1/chatlab/",
        )
        connected, _ = await communicator.connect()
        assert connected is False

    async def test_invalid_jwt_rejects_ws_connection(self):
        """WS connection with a malformed JWT is treated as unauthenticated."""
        await self._make_user_and_simulation()

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            "/ws/v1/chatlab/",
            headers=[(b"authorization", b"Bearer not.a.real.token")],
        )
        connected, _ = await communicator.connect()
        assert connected is False

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
            "/ws/v1/chatlab/",
            headers=[(b"authorization", f"Bearer {token}".encode())],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to(
            {
                "event_type": "session.hello",
                "payload": {"simulation_id": simulation.id},
            }
        )
        response = await communicator.receive_json_from()
        assert response["event_type"] == "error"
        assert "access" in response["payload"]["code"]

        await communicator.disconnect()

    async def test_query_param_jwt_rejected_e2e(self):
        """Query-param JWT tokens are no longer accepted end-to-end."""
        user, _simulation = await self._make_user_and_simulation()
        token = create_access_token(user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/v1/chatlab/?token={token}",
        )
        connected, _ = await communicator.connect()
        # Without header-based auth, connection should be rejected
        assert connected is False

    async def test_jwt_with_account_header_e2e(self):
        """Full stack: Bearer token + X-Account-UUID header resolves both user and account."""
        from asgiref.sync import sync_to_async

        from apps.accounts.services import get_default_account_for_user

        user, simulation = await self._make_user_and_simulation()
        account = await sync_to_async(get_default_account_for_user)(user)

        # Link simulation to account
        simulation.account = account
        await simulation.asave(update_fields=["account"])

        token = create_access_token(user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            "/ws/v1/chatlab/",
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-account-uuid", str(account.uuid).encode()),
            ],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to(
            {
                "event_type": "session.hello",
                "payload": {"simulation_id": simulation.id},
            }
        )
        response = await communicator.receive_json_from()
        assert response["event_type"] == "session.ready"
        assert response["payload"]["simulation_id"] == simulation.id

        await communicator.disconnect()

    async def test_account_context_wrong_account_denied(self):
        """Valid auth but wrong account UUID denies simulation access."""
        from apps.accounts.models import Account

        user, simulation = await self._make_user_and_simulation()
        token = create_access_token(user)

        # Create a different account the user doesn't have access to
        other_account = await Account.objects.acreate(
            name="Other Org",
            slug=f"other-org-e2e-{uuid4().hex[:6]}",
            account_type=Account.AccountType.ORGANIZATION,
        )

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            "/ws/v1/chatlab/",
            headers=[
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-account-uuid", str(other_account.uuid).encode()),
            ],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to(
            {
                "event_type": "session.hello",
                "payload": {"simulation_id": simulation.id},
            }
        )
        response = await communicator.receive_json_from()
        assert response["event_type"] == "error"
        assert response["payload"]["code"] == "access_denied"

        await communicator.disconnect()

    async def test_no_query_param_account_selection_e2e(self):
        """Query-param account_uuid is not accepted for account context."""
        from urllib.parse import urlencode

        from apps.accounts.models import Account

        user, _simulation = await self._make_user_and_simulation()
        token = create_access_token(user)

        # Create other account and try to select it via query param
        other_account = await Account.objects.acreate(
            name="QP Org",
            slug=f"qp-org-{uuid4().hex[:6]}",
            account_type=Account.AccountType.ORGANIZATION,
        )

        qs = urlencode({"account_uuid": str(other_account.uuid)}).encode()
        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/v1/chatlab/?{qs.decode()}",
            headers=[(b"authorization", f"Bearer {token}".encode())],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        # The query param should be ignored; account should resolve to default
        # (the user's personal account), not the query-param one
        await communicator.disconnect()


# ---------------------------------------------------------------------------
# End-to-end: NotificationsConsumer authentication
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestNotificationsWebSocketEndToEnd:
    """Integration tests: NotificationsConsumer auth through SessionOrJWTAuthMiddlewareStack.

    Verifies that:
    - Anonymous connections are rejected with close code 4001 (not HTTP 403)
    - JWT-authenticated users can connect successfully
    - Query-param tokens are no longer accepted
    """

    async def _make_user(self):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole

        User = get_user_model()
        role, _ = await UserRole.objects.aget_or_create(title="WS Notif E2E Test")
        return await User.objects.acreate(email=f"ws_notif_{uuid4().hex[:6]}@test.com", role=role)

    async def test_anonymous_connection_is_rejected_with_close_code(self):
        """Anonymous WS connection to notifications is rejected with close code 4001.

        The consumer must call accept() before close() so the client receives
        the close code rather than an HTTP 403 upgrade rejection.
        """
        communicator = WebsocketCommunicator(_make_ws_app(), "/ws/notifications/")
        connected, _ = await communicator.connect()
        # Consumer accepts then immediately closes with 4001 for unauthenticated users.
        # A plain HTTP 403 rejection would have returned connected=False here.
        assert connected is True

        # The close frame carrying code 4001 arrives as the next output message.
        close_message = await communicator.receive_output()
        assert close_message["type"] == "websocket.close"
        assert close_message.get("code") == 4001

        await communicator.disconnect()

    async def test_jwt_in_header_allows_notifications_connection(self):
        """JWT-authenticated user can connect to the notifications WebSocket."""
        user = await self._make_user()
        token = create_access_token(user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            "/ws/notifications/",
            headers=[(b"authorization", f"Bearer {token}".encode())],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.disconnect()

    async def test_query_param_jwt_rejected_for_notifications(self):
        """Query-param JWT tokens are no longer accepted for notifications."""
        user = await self._make_user()
        token = create_access_token(user)

        communicator = WebsocketCommunicator(
            _make_ws_app(),
            f"/ws/notifications/?token={token}",
        )
        connected, _ = await communicator.connect()
        # Without header auth, user is anonymous → accepted then closed with 4001
        assert connected is True

        close_message = await communicator.receive_output()
        assert close_message["type"] == "websocket.close"
        assert close_message.get("code") == 4001

        await communicator.disconnect()

    async def test_invalid_jwt_is_rejected_with_close_code(self):
        """Invalid JWT token results in rejection with close code 4001."""
        communicator = WebsocketCommunicator(
            _make_ws_app(),
            "/ws/notifications/",
            headers=[(b"authorization", b"Bearer not.a.valid.token")],
        )
        connected, _ = await communicator.connect()
        # Invalid JWT falls back to AnonymousUser; consumer accepts then closes.
        assert connected is True

        close_message = await communicator.receive_output()
        assert close_message["type"] == "websocket.close"
        assert close_message.get("code") == 4001

        await communicator.disconnect()
