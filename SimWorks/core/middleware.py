import json
import uuid

from django.http import HttpRequest, HttpResponse


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
    - Adds X-Correlation-ID to response headers

    Usage:
        # In views or other code
        correlation_id = request.correlation_id
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

        # Process request
        response = self.get_response(request)

        # Add to response headers
        response[self.HEADER_NAME] = correlation_id

        return response
