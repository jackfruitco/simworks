"""Tests for JWT authentication.

Tests that:
1. Token generation works correctly
2. Token validation works correctly
3. Token refresh flow works
4. Invalid/expired tokens are rejected
5. Protected endpoints work with JWT auth
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from django.test import Client, override_settings

from api.v1.auth import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    create_tokens,
    decode_access_token,
    decode_refresh_token,
    get_jwt_secret,
    refresh_access_token,
)


@pytest.fixture
def test_user(django_user_model):
    """Create a test user with a role."""
    from apps.accounts.models import UserRole

    role = UserRole.objects.create(title="Test Role JWT")
    return django_user_model.objects.create_user(
        password="testpass123",
        email="jwt@example.com",
        role=role,
    )


class TestTokenGeneration:
    """Tests for JWT token generation."""

    def test_create_access_token_returns_string(self, test_user):
        """Access token is a non-empty string."""
        token = create_access_token(test_user)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_is_valid_jwt(self, test_user):
        """Access token is a valid JWT that can be decoded."""
        token = create_access_token(test_user)
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])

        assert payload["sub"] == str(test_user.pk)
        assert payload["email"] == test_user.email
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_create_refresh_token_returns_string(self, test_user):
        """Refresh token is a non-empty string."""
        token = create_refresh_token(test_user)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token_is_valid_jwt(self, test_user):
        """Refresh token is a valid JWT with correct type."""
        token = create_refresh_token(test_user)
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])

        assert payload["sub"] == str(test_user.pk)
        assert payload["type"] == "refresh"
        assert "exp" in payload
        assert "iat" in payload

    def test_create_tokens_returns_all_fields(self, test_user):
        """create_tokens returns access_token, refresh_token, expires_in, token_type."""
        tokens = create_tokens(test_user)

        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert "expires_in" in tokens
        assert "token_type" in tokens
        assert tokens["token_type"] == "Bearer"
        assert isinstance(tokens["expires_in"], int)


class TestTokenValidation:
    """Tests for JWT token validation."""

    def test_decode_access_token_valid(self, test_user):
        """Valid access token decodes successfully."""
        token = create_access_token(test_user)
        payload = decode_access_token(token)

        assert payload["sub"] == str(test_user.pk)
        assert payload["type"] == "access"

    def test_decode_access_token_wrong_type_raises(self, test_user):
        """Refresh token cannot be used as access token."""
        token = create_refresh_token(test_user)

        with pytest.raises(InvalidTokenError, match="not an access token"):
            decode_access_token(token)

    def test_decode_access_token_expired_raises(self, test_user):
        """Expired access token raises InvalidTokenError."""
        # Create token that expired 1 second ago
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(test_user.pk),
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(seconds=1),
        }
        token = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")

        with pytest.raises(InvalidTokenError, match="expired"):
            decode_access_token(token)

    def test_decode_access_token_invalid_signature_raises(self, test_user):
        """Token with invalid signature raises InvalidTokenError."""
        payload = {
            "sub": str(test_user.pk),
            "type": "access",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")

        with pytest.raises(InvalidTokenError, match="Invalid token"):
            decode_access_token(token)

    def test_decode_refresh_token_valid(self, test_user):
        """Valid refresh token decodes successfully."""
        token = create_refresh_token(test_user)
        payload = decode_refresh_token(token)

        assert payload["sub"] == str(test_user.pk)
        assert payload["type"] == "refresh"

    def test_decode_refresh_token_wrong_type_raises(self, test_user):
        """Access token cannot be used as refresh token."""
        token = create_access_token(test_user)

        with pytest.raises(InvalidTokenError, match="not a refresh token"):
            decode_refresh_token(token)


class TestTokenRefresh:
    """Tests for token refresh flow."""

    def test_refresh_access_token_returns_new_token(self, test_user):
        """Refresh token generates new access token."""
        refresh = create_refresh_token(test_user)
        result = refresh_access_token(refresh)

        assert "access_token" in result
        assert "expires_in" in result
        assert "token_type" in result
        assert result["token_type"] == "Bearer"

        # Verify new token is valid
        payload = decode_access_token(result["access_token"])
        assert payload["sub"] == str(test_user.pk)

    def test_refresh_access_token_invalid_refresh_raises(self):
        """Invalid refresh token raises InvalidTokenError."""
        with pytest.raises(InvalidTokenError):
            refresh_access_token("invalid-token")

    def test_refresh_access_token_expired_refresh_raises(self, test_user):
        """Expired refresh token raises InvalidTokenError."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(test_user.pk),
            "type": "refresh",
            "iat": now - timedelta(days=8),
            "exp": now - timedelta(seconds=1),
        }
        token = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")

        with pytest.raises(InvalidTokenError, match="expired"):
            refresh_access_token(token)

    def test_refresh_access_token_inactive_user_raises(self, test_user):
        """Refresh for inactive user raises InvalidTokenError."""
        refresh = create_refresh_token(test_user)

        # Deactivate user
        test_user.is_active = False
        test_user.save()

        with pytest.raises(InvalidTokenError, match="User not found or inactive"):
            refresh_access_token(refresh)


@pytest.mark.django_db
class TestAuthEndpoints:
    """Tests for authentication API endpoints."""

    def test_obtain_token_success(self, test_user):
        """Valid credentials return tokens."""
        client = Client()
        response = client.post(
            "/api/v1/auth/token/",
            data={"email": "jwt@example.com", "password": "testpass123"},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "expires_in" in data
        assert data["token_type"] == "Bearer"

    def test_obtain_token_invalid_credentials(self, test_user):
        """Invalid credentials return 401."""
        client = Client()
        response = client.post(
            "/api/v1/auth/token/",
            data={"email": "jwt@example.com", "password": "wrongpassword"},
            content_type="application/json",
        )

        assert response.status_code == 401

    def test_obtain_token_missing_fields(self):
        """Missing credentials return 422."""
        client = Client()
        response = client.post(
            "/api/v1/auth/token/",
            data={},
            content_type="application/json",
        )

        assert response.status_code == 422

    def test_obtain_token_inactive_user(self, test_user):
        """Inactive user cannot obtain tokens."""
        test_user.is_active = False
        test_user.save()

        client = Client()
        response = client.post(
            "/api/v1/auth/token/",
            data={"email": "jwt@example.com", "password": "testpass123"},
            content_type="application/json",
        )

        assert response.status_code == 401

    def test_refresh_token_success(self, test_user):
        """Valid refresh token returns new access token."""
        tokens = create_tokens(test_user)

        client = Client()
        response = client.post(
            "/api/v1/auth/token/refresh/",
            data={"refresh_token": tokens["refresh_token"]},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "expires_in" in data

    def test_refresh_token_invalid(self):
        """Invalid refresh token returns 401."""
        client = Client()
        response = client.post(
            "/api/v1/auth/token/refresh/",
            data={"refresh_token": "invalid-token"},
            content_type="application/json",
        )

        assert response.status_code == 401


@pytest.mark.django_db
class TestJWTProtectedEndpoints:
    """Tests for endpoints protected by JWT authentication."""

    def test_jwt_endpoint_without_token_returns_401(self):
        """Accessing JWT-protected endpoint without token returns 401."""
        client = Client()
        response = client.get("/api/v1/health/jwt")

        assert response.status_code == 401

    def test_jwt_endpoint_with_invalid_token_returns_401(self):
        """Accessing JWT-protected endpoint with invalid token returns 401."""
        client = Client()
        response = client.get(
            "/api/v1/health/jwt",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )

        assert response.status_code == 401

    def test_jwt_endpoint_with_valid_token_returns_200(self, test_user):
        """Accessing JWT-protected endpoint with valid token succeeds."""
        token = create_access_token(test_user)

        client = Client()
        response = client.get(
            "/api/v1/health/jwt",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_jwt_endpoint_with_expired_token_returns_401(self, test_user):
        """Accessing JWT-protected endpoint with expired token returns 401."""
        # Create expired token
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(test_user.pk),
            "email": test_user.email,
            "type": "access",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(seconds=1),
        }
        token = jwt.encode(payload, get_jwt_secret(), algorithm="HS256")

        client = Client()
        response = client.get(
            "/api/v1/health/jwt",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == 401

    def test_jwt_endpoint_with_refresh_token_returns_401(self, test_user):
        """Using refresh token for API access returns 401."""
        refresh = create_refresh_token(test_user)

        client = Client()
        response = client.get(
            "/api/v1/health/jwt",
            HTTP_AUTHORIZATION=f"Bearer {refresh}",
        )

        assert response.status_code == 401


@pytest.mark.django_db
class TestFullAuthFlow:
    """Integration tests for complete authentication flow."""

    def test_login_access_refresh_flow(self, test_user):
        """Test complete flow: login -> access -> refresh -> access."""
        client = Client()

        # Step 1: Login
        login_response = client.post(
            "/api/v1/auth/token/",
            data={"email": "jwt@example.com", "password": "testpass123"},
            content_type="application/json",
        )
        assert login_response.status_code == 200
        tokens = login_response.json()

        # Step 2: Access protected resource
        access_response = client.get(
            "/api/v1/health/jwt",
            HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
        )
        assert access_response.status_code == 200

        # Step 3: Refresh token
        refresh_response = client.post(
            "/api/v1/auth/token/refresh/",
            data={"refresh_token": tokens["refresh_token"]},
            content_type="application/json",
        )
        assert refresh_response.status_code == 200
        new_tokens = refresh_response.json()

        # Step 4: Access with new token
        final_response = client.get(
            "/api/v1/health/jwt",
            HTTP_AUTHORIZATION=f"Bearer {new_tokens['access_token']}",
        )
        assert final_response.status_code == 200


@pytest.mark.django_db
class TestDualAuth:
    """Tests for DualAuth class that supports both session and JWT authentication."""

    def test_dual_auth_with_session(self, test_user):
        """DualAuth accepts session-authenticated requests (web clients)."""
        client = Client()
        client.force_login(test_user)

        # Access messages endpoint (uses DualAuth) with session auth
        from simulation.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Test Patient",
        )

        response = client.get(f"/api/v1/simulations/{sim.pk}/messages/")
        assert response.status_code == 200

    def test_dual_auth_with_jwt(self, test_user):
        """DualAuth accepts JWT-authenticated requests (mobile clients)."""
        token = create_access_token(test_user)
        client = Client()

        # Access messages endpoint with JWT auth
        from simulation.models import Simulation

        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Test Patient",
        )

        response = client.get(
            f"/api/v1/simulations/{sim.pk}/messages/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert response.status_code == 200

    def test_dual_auth_prefers_session_over_jwt(self, test_user, django_user_model):
        """When both session and JWT are present, session takes precedence."""
        from apps.accounts.models import UserRole
        from simulation.models import Simulation

        # Create a second user for JWT
        role = UserRole.objects.create(title="Test Role JWT2")
        other_user = django_user_model.objects.create_user(
            password="pass123",
            email="other@example.com",
            role=role,
        )

        # Session user owns the simulation
        sim = Simulation.objects.create(
            user=test_user,
            sim_patient_full_name="Test Patient",
        )

        # JWT is for other_user who doesn't own the simulation
        token = create_access_token(other_user)

        client = Client()
        client.force_login(test_user)  # Session auth as sim owner

        # Should succeed because session auth (test_user) takes precedence
        response = client.get(
            f"/api/v1/simulations/{sim.pk}/messages/",
            HTTP_AUTHORIZATION=f"Bearer {token}",  # JWT for non-owner
        )
        assert response.status_code == 200

    def test_dual_auth_rejects_unauthenticated(self):
        """DualAuth rejects requests with no authentication."""
        client = Client()

        response = client.get("/api/v1/simulations/1/messages/")
        assert response.status_code == 401

    def test_dual_auth_rejects_invalid_jwt(self):
        """DualAuth rejects requests with invalid JWT and no session."""
        client = Client()

        response = client.get(
            "/api/v1/simulations/1/messages/",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        assert response.status_code == 401
