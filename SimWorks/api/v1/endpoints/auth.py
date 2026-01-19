"""Authentication endpoints for API v1.

Provides JWT token obtain and refresh endpoints for mobile clients.
"""

from django.contrib.auth import authenticate
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from pydantic import BaseModel, Field

from api.v1.auth import InvalidTokenError, create_tokens, refresh_access_token
from config.logging import get_logger
from core.ratelimit import auth_rate_limit

logger = get_logger(__name__)

router = Router(tags=["auth"])


class LoginRequest(BaseModel):
    """Request body for token obtain endpoint."""

    username: str = Field(
        ...,
        min_length=1,
        description="Username or email",
        examples=["john.doe"],
    )
    password: str = Field(
        ...,
        min_length=1,
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
    description="Authenticate with username/password and receive JWT tokens.",
)
@auth_rate_limit
def obtain_token(request: HttpRequest, body: LoginRequest) -> TokenResponse:
    """Obtain JWT access and refresh tokens.

    Authenticates the user with username/password and returns:
    - access_token: Short-lived token for API authentication
    - refresh_token: Long-lived token for obtaining new access tokens
    - expires_in: Access token lifetime in seconds
    - token_type: Always "Bearer"

    Use the access_token in the Authorization header:
        Authorization: Bearer <access_token>
    """
    user = authenticate(request, username=body.username, password=body.password)

    if user is None:
        logger.warning("auth.login_failed", username=body.username, reason="invalid_credentials")
        raise HttpError(401, "Invalid credentials")

    if not user.is_active:
        logger.warning("auth.login_failed", username=body.username, reason="user_inactive")
        raise HttpError(401, "User account is disabled")

    tokens = create_tokens(user)
    logger.info("auth.tokens_issued", user_id=user.pk, username=user.username)

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
        logger.warning("auth.token_refresh_failed", error=str(e))
        raise HttpError(401, str(e))
