import json
import uuid

from django.http import HttpRequest, HttpResponse

from config.logging import bind_context, bind_correlation_id, clear_context


class HealthCheckMiddleware:
    """Handle health check endpoint at /health."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health":
            s = {"status": 200, "message": "OK"}
            return HttpResponse(
                status=200, content=json.dumps(s), content_type="application/json"
            )
        return self.get_response(request)


class CorrelationIDMiddleware:
    """Middleware to propagate X-Correlation-ID header.

    - Reads X-Correlation-ID from incoming request headers
    - Generates a new UUID if not present
    - Attaches correlation_id to request object
    - Binds correlation_id to structlog context for automatic inclusion in logs
    - Adds X-Correlation-ID to response headers
    - Clears structlog context after request completes

    Usage:
        # In views or other code
        correlation_id = request.correlation_id

        # Logging will automatically include correlation_id
        from config.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Processing request")  # correlation_id included automatically
    """

    HEADER_NAME = "X-Correlation-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Extract or generate correlation ID
        correlation_id = request.headers.get(self.HEADER_NAME)
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Attach to request for use in views/services
        request.correlation_id = correlation_id

        # Bind to structlog context for automatic inclusion in all logs
        bind_correlation_id(correlation_id)

        # Optionally bind user context if authenticated
        if hasattr(request, "user") and request.user.is_authenticated:
            bind_context(user_id=request.user.pk)

        try:
            # Process request
            response = self.get_response(request)

            # Add to response headers
            response[self.HEADER_NAME] = correlation_id

            return response
        finally:
            # Clear structlog context to prevent leakage between requests
            clear_context()
