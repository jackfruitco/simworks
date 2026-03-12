"""API v1 main entry point.

This module creates and configures the NinjaAPI instance for v1.
"""

from datetime import UTC, datetime

from django.http import HttpRequest
from ninja import NinjaAPI
from ninja.errors import HttpError, ValidationError
from ninja.security import django_auth

from api.v1.auth import JWTAuth
from api.v1.endpoints.auth import router as auth_router
from api.v1.endpoints.conversations import router as conversations_router
from api.v1.endpoints.events import router as events_router
from api.v1.endpoints.messages import router as messages_router
from api.v1.endpoints.modifiers import router as modifiers_router
from api.v1.endpoints.simulations import router as simulations_router
from api.v1.endpoints.tools import router as tools_router
from api.v1.endpoints.trainerlab import router as trainerlab_router
from api.v1.schemas.common import ErrorResponse, HealthResponse
from apps.common.ratelimit import RateLimitExceeded
from config.logging import get_logger

logger = get_logger(__name__)


def get_correlation_id(request: HttpRequest) -> str | None:
    """Extract correlation ID from request if available."""
    return getattr(request, "correlation_id", None)


def create_error_response(
    request: HttpRequest,
    error_type: str,
    title: str,
    status: int,
    detail: str,
) -> ErrorResponse:
    """Create a standardized error response."""
    return ErrorResponse(
        type=error_type,
        title=title,
        status=status,
        detail=detail,
        instance=request.path,
        correlation_id=get_correlation_id(request),
    )


# Create the API instance
api = NinjaAPI(
    title="SimWorks API",
    version="1.0.0",
    description="REST API for SimWorks medical training platform",
    urls_namespace="api-v1",
)


# Custom exception handlers
@api.exception_handler(ValidationError)
def validation_error_handler(request: HttpRequest, exc: ValidationError):
    """Handle Pydantic validation errors."""
    # Extract first error message for detail
    errors = exc.errors
    if errors:
        first_error = errors[0]
        loc = ".".join(str(x) for x in first_error.get("loc", []))
        msg = first_error.get("msg", "Validation error")
        detail = f"{loc}: {msg}" if loc else msg
    else:
        detail = "Validation error"

    return api.create_response(
        request,
        create_error_response(
            request,
            error_type="validation_error",
            title="Invalid input",
            status=422,
            detail=detail,
        ).model_dump(),
        status=422,
    )


@api.exception_handler(RateLimitExceeded)
def rate_limit_error_handler(request: HttpRequest, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors."""
    response = api.create_response(
        request,
        create_error_response(
            request,
            error_type="rate_limit_exceeded",
            title="Too many requests",
            status=429,
            detail=str(exc.message),
        ).model_dump(),
        status=429,
    )
    response["Retry-After"] = str(exc.retry_after)
    return response


@api.exception_handler(HttpError)
def http_error_handler(request: HttpRequest, exc: HttpError):
    """Handle explicit HTTP errors."""
    return api.create_response(
        request,
        create_error_response(
            request,
            error_type="http_error",
            title="Request error",
            status=exc.status_code,
            detail=str(exc.message),
        ).model_dump(),
        status=exc.status_code,
    )


@api.exception_handler(Exception)
def generic_error_handler(request: HttpRequest, exc: Exception):
    """Handle unexpected errors."""
    # Log the actual error for debugging (correlation_id included automatically via structlog)
    logger.exception("api.unexpected_error", exc_info=exc, path=request.path)

    return api.create_response(
        request,
        create_error_response(
            request,
            error_type="internal_error",
            title="Internal server error",
            status=500,
            detail="An unexpected error occurred",
        ).model_dump(),
        status=500,
    )


def _build_health_response() -> HealthResponse:
    """Build a standard health check response."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(UTC),
    )


# Health check endpoint (unauthenticated)
@api.get(
    "/health",
    response=HealthResponse,
    tags=["system"],
    summary="Health check",
    description="Returns the API health status and current timestamp.",
)
def health_check(request: HttpRequest) -> HealthResponse:
    """Simple health check endpoint."""
    return _build_health_response()


# Authenticated health check (session auth - for web clients)
@api.get(
    "/health/auth",
    response=HealthResponse,
    auth=django_auth,
    tags=["system"],
    summary="Authenticated health check (session)",
    description="Health check that requires session authentication (web clients).",
)
def health_check_auth(request: HttpRequest) -> HealthResponse:
    """Health check requiring session authentication."""
    return _build_health_response()


# JWT-authenticated health check (for mobile clients)
@api.get(
    "/health/jwt",
    response=HealthResponse,
    auth=JWTAuth(),
    tags=["system"],
    summary="Authenticated health check (JWT)",
    description="Health check that requires JWT authentication (mobile clients).",
)
def health_check_jwt(request: HttpRequest) -> HealthResponse:
    """Health check requiring JWT authentication."""
    return _build_health_response()


# Register routers
api.add_router("/auth", auth_router)
api.add_router("/simulations", simulations_router)
api.add_router("/simulations", conversations_router)  # Conversations nested under simulations
api.add_router("/simulations", messages_router)  # Messages are nested under simulations
api.add_router("/simulations", events_router)  # Events (catch-up) are nested under simulations
api.add_router(
    "/simulations", tools_router
)  # Tools (JSON payloads/actions) nested under simulations
api.add_router("/config", modifiers_router)  # Configuration endpoints (modifiers, etc.)
api.add_router("/trainerlab", trainerlab_router)
