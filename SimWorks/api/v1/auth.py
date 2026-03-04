"""JWT authentication for API v1.

Provides JWT-based authentication for mobile clients.
Web clients continue to use session-based authentication.
"""

from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
import jwt
from ninja.security import HttpBearer

logger = logging.getLogger(__name__)

User = get_user_model()


class InvalidTokenError(Exception):
    """Raised when a token is invalid or expired."""


class DualAuth(HttpBearer):
    """Combined session + JWT authentication for Django Ninja.

    Tries session auth first (for web clients), then JWT (for mobile clients).
    This allows the same endpoint to serve both web and mobile clients.

    Usage:
        @router.post("/messages/", auth=DualAuth())
        def create_message(request):
            # request.auth contains the authenticated user
            return {"user": request.auth.email}
    """

    def __call__(self, request) -> User | None:
        """Check session auth first, then fall back to JWT."""
        # Try session auth (web clients)
        if request.user and request.user.is_authenticated:
            return request.user

        # Fall back to JWT auth (mobile clients)
        return super().__call__(request)

    def authenticate(self, request, token: str) -> User | None:
        """Validate JWT token and return the associated user."""
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if not user_id:
                return None

            user = User.objects.filter(pk=user_id, is_active=True).first()
            return user

        except InvalidTokenError as e:
            logger.debug("JWT authentication failed: %s", e)
            return None
        except Exception as e:
            logger.warning("Unexpected JWT authentication error: %s", e)
            return None


class JWTAuth(HttpBearer):
    """JWT Bearer token authentication for Django Ninja.

    Usage:
        @router.get("/protected/", auth=JWTAuth())
        def protected_endpoint(request):
            # request.auth contains the authenticated user
            return {"user": request.auth.email}
    """

    def authenticate(self, request, token: str) -> User | None:
        """Validate JWT token and return the associated user.

        Args:
            request: The HTTP request
            token: The JWT token from Authorization header

        Returns:
            User instance if valid, None otherwise
        """
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if not user_id:
                return None

            user = User.objects.filter(pk=user_id, is_active=True).first()
            return user

        except InvalidTokenError as e:
            logger.debug("JWT authentication failed: %s", e)
            return None
        except Exception as e:
            logger.warning("Unexpected JWT authentication error: %s", e)
            return None


def get_jwt_secret() -> str:
    """Get the JWT signing secret.

    Requires JWT_SECRET_KEY to be set in Django settings.
    Falls back to SECRET_KEY only in DEBUG mode with a warning.
    """
    jwt_secret = getattr(settings, "JWT_SECRET_KEY", None)
    if jwt_secret:
        return jwt_secret

    if settings.DEBUG:
        logger.warning(
            "JWT_SECRET_KEY not set, falling back to SECRET_KEY. Set JWT_SECRET_KEY in production."
        )
        return settings.SECRET_KEY

    raise ValueError(
        "JWT_SECRET_KEY must be set in Django settings for production. "
        "Generate a secure secret with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
    )


def get_access_token_lifetime() -> int:
    """Get access token lifetime in seconds."""
    return getattr(settings, "JWT_ACCESS_TOKEN_LIFETIME", 3600)  # 1 hour default


def get_refresh_token_lifetime() -> int:
    """Get refresh token lifetime in seconds."""
    return getattr(settings, "JWT_REFRESH_TOKEN_LIFETIME", 86400 * 7)  # 7 days default


def create_access_token(user: User) -> str:
    """Create a JWT access token for a user.

    Args:
        user: The user to create a token for

    Returns:
        Encoded JWT access token
    """
    now = datetime.now(UTC)
    lifetime = get_access_token_lifetime()
    expires_at = now + timedelta(seconds=lifetime)

    payload = {
        "sub": str(user.pk),
        "email": user.email,
        "type": "access",
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def create_refresh_token(user: User) -> str:
    """Create a JWT refresh token for a user.

    Args:
        user: The user to create a token for

    Returns:
        Encoded JWT refresh token
    """
    now = datetime.now(UTC)
    lifetime = get_refresh_token_lifetime()
    expires_at = now + timedelta(seconds=lifetime)

    payload = {
        "sub": str(user.pk),
        "type": "refresh",
        "iat": now,
        "exp": expires_at,
    }

    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def create_tokens(user: User) -> dict[str, Any]:
    """Create both access and refresh tokens for a user.

    Args:
        user: The user to create tokens for

    Returns:
        Dictionary with access_token, refresh_token, expires_in, and token_type
    """
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "expires_in": get_access_token_lifetime(),
        "token_type": "Bearer",
    }


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: The JWT token to decode

    Returns:
        The decoded payload

    Raises:
        InvalidTokenError: If token is invalid, expired, or wrong type
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])

        if payload.get("type") != "access":
            raise InvalidTokenError("Token is not an access token")

        return payload

    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Token has expired") from None
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(f"Invalid token: {e}") from None


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT refresh token.

    Args:
        token: The JWT token to decode

    Returns:
        The decoded payload

    Raises:
        InvalidTokenError: If token is invalid, expired, or wrong type
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])

        if payload.get("type") != "refresh":
            raise InvalidTokenError("Token is not a refresh token")

        return payload

    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Refresh token has expired") from None
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(f"Invalid refresh token: {e}") from None


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Generate a new access token using a refresh token.

    Args:
        refresh_token: The refresh token

    Returns:
        Dictionary with new access_token, expires_in, and token_type

    Raises:
        InvalidTokenError: If refresh token is invalid or user not found
    """
    payload = decode_refresh_token(refresh_token)
    user_id = payload.get("sub")

    if not user_id:
        raise InvalidTokenError("Invalid refresh token payload")

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user:
        raise InvalidTokenError("User not found or inactive")

    return {
        "access_token": create_access_token(user),
        "expires_in": get_access_token_lifetime(),
        "token_type": "Bearer",
    }
