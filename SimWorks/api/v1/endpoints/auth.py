"""Authentication endpoints for API v1.

Provides JWT token obtain and refresh endpoints for mobile clients.
"""

from django.contrib.auth import authenticate
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from pydantic import BaseModel, Field

from api.v1.auth import InvalidTokenError, create_tokens, refresh_access_token

try:
    # Optional; depends on whether refresh sessions are persisted server-side.
    from api.v1.auth import revoke_refresh_token  # type: ignore
except Exception:  # pragma: no cover
    revoke_refresh_token = None

from apps.common.ratelimit import auth_rate_limit
from config.logging import get_logger

logger = get_logger(__name__)

router = Router(tags=["auth"])


class LoginRequest(BaseModel):
    """Request body for token obtain endpoint."""

    email: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="User email address",
        examples=["user@example.com"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="User password",
        examples=["secret123"],
    )


class TokenResponse(BaseModel):
    """Response for successful token generation."""

    access_token: str = Field(
        ...,
        description="JWT access token for API authentication",
    )
    refresh_token: str = Field(
        ...,
        description="JWT refresh token for obtaining new access tokens",
    )
    expires_in: int = Field(
        ...,
        description="Access token lifetime in seconds",
        examples=[3600],
    )
    token_type: str = Field(
        default="Bearer",
        description="Token type (always 'Bearer')",
    )


class RefreshRequest(BaseModel):
    """Request body for token refresh endpoint."""

    refresh_token: str = Field(
        ...,
        min_length=1,
        description="JWT refresh token",
    )


class RefreshResponse(BaseModel):
    """Response for successful token refresh."""

    access_token: str = Field(
        ...,
        description="New JWT access token",
    )
    refresh_token: str | None = Field(
        default=None,
        description="(Optional) Rotated refresh token, if rotation is enabled.",
    )
    expires_in: int = Field(
        ...,
        description="Access token lifetime in seconds",
        examples=[3600],
    )
    token_type: str = Field(
        default="Bearer",
        description="Token type (always 'Bearer')",
    )


@router.post(
    "/token/",
    response=TokenResponse,
    summary="Obtain JWT tokens",
    description="Authenticate with email/password and receive JWT tokens.",
)
@auth_rate_limit
def obtain_token(request: HttpRequest, body: LoginRequest) -> TokenResponse:
    """Obtain JWT access and refresh tokens.

    Authenticates the user with email/password and returns:
    - access_token: Short-lived token for API authentication
    - refresh_token: Long-lived token for obtaining new access tokens
    - expires_in: Access token lifetime in seconds
    - token_type: Always "Bearer"

    Use the access_token in the Authorization header:
        Authorization: Bearer <access_token>
    """
    # Django authenticate expects 'username' kwarg, but our User model uses email as USERNAME_FIELD
    user = authenticate(request, username=body.email, password=body.password)

    if user is None:
        logger.warning("auth.login_failed", reason="invalid_credentials")
        raise HttpError(401, "Invalid credentials")

    if not user.is_active:
        # Use same error message to prevent user enumeration
        logger.warning("auth.login_failed", reason="user_inactive")
        raise HttpError(401, "Invalid credentials")

    tokens = create_tokens(user)
    logger.info("auth.tokens_issued", user_id=user.pk)

    return TokenResponse(**tokens)


@router.post(
    "/token/refresh/",
    response=RefreshResponse,
    summary="Refresh access token",
    description="Use a refresh token to obtain a new access token.",
)
@auth_rate_limit
def refresh_token(request: HttpRequest, body: RefreshRequest) -> RefreshResponse:
    """Refresh an access token using a refresh token.

    When your access token expires, use this endpoint with your
    refresh token to obtain a new access token without re-authenticating.

    The refresh token remains valid until its own expiration.
    """
    try:
        result = refresh_access_token(body.refresh_token)
        return RefreshResponse(**result)

    except InvalidTokenError as e:
        # Log full error but return generic message to prevent information leakage
        logger.warning("auth.token_refresh_failed", error=str(e))
        raise HttpError(401, "Invalid or expired refresh token") from None


class LogoutRequest(BaseModel):
    """Request body for logout endpoint."""

    refresh_token: str = Field(
        ...,
        min_length=1,
        description="Refresh token to revoke",
    )


@router.post(
    "/logout/",
    summary="Logout",
    description="Revoke a refresh token/session (server-side), then the client should delete tokens locally.",
)
@auth_rate_limit
def logout(request: HttpRequest, body: LogoutRequest):
    """Logout by revoking the refresh token/session.

    Best practice for token-based auth is to revoke the refresh token (or its backing session) server-side.
    If server-side revocation is not implemented, this endpoint returns 501.
    """
    if revoke_refresh_token is None:
        logger.error("auth.logout_not_supported")
        raise HttpError(501, "Logout not supported")

    try:
        revoke_refresh_token(body.refresh_token)
        logger.info("auth.logout", result="revoked")
        return {"detail": "ok"}
    except InvalidTokenError as e:
        # For idempotency, treat invalid/expired as already-logged-out.
        logger.info("auth.logout", result="already_invalid", error=str(e))
        return {"detail": "ok"}
