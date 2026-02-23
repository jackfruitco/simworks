"""Tests for CorrelationIDMiddleware.

Tests that the middleware:
1. Generates a UUID correlation ID when not provided
2. Propagates existing correlation ID from request header
3. Attaches correlation ID to request object
4. Adds correlation ID to response header
"""

import re
import uuid

import pytest
from django.test import Client, RequestFactory

from apps.common.middleware import CorrelationIDMiddleware

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class TestCorrelationIDMiddleware:
    """Tests for CorrelationIDMiddleware."""

    def test_generates_correlation_id_when_missing(self):
        """When no X-Correlation-ID header is present, middleware generates one."""

        def mock_get_response(request):
            # Verify correlation ID was attached to request
            assert hasattr(request, "correlation_id")
            assert UUID_PATTERN.match(request.correlation_id)
            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        factory = RequestFactory()
        request = factory.get("/test/")

        response = middleware(request)

        # Verify response has correlation ID header
        assert "X-Correlation-ID" in response
        assert UUID_PATTERN.match(response["X-Correlation-ID"])

    def test_propagates_existing_correlation_id(self):
        """When X-Correlation-ID header is present, middleware uses it."""
        existing_id = str(uuid.uuid4())

        def mock_get_response(request):
            # Verify existing ID was used
            assert request.correlation_id == existing_id
            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        factory = RequestFactory()
        request = factory.get("/test/", HTTP_X_CORRELATION_ID=existing_id)

        response = middleware(request)

        # Verify same ID in response
        assert response["X-Correlation-ID"] == existing_id

    def test_attaches_correlation_id_to_request(self):
        """Correlation ID is accessible via request.correlation_id."""
        captured_id = None

        def mock_get_response(request):
            nonlocal captured_id
            captured_id = request.correlation_id
            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        factory = RequestFactory()
        request = factory.get("/test/")

        middleware(request)

        assert captured_id is not None
        assert UUID_PATTERN.match(captured_id)

    def test_adds_correlation_id_to_response_header(self):
        """X-Correlation-ID header is present in response."""

        def mock_get_response(request):
            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        factory = RequestFactory()
        request = factory.get("/test/")

        response = middleware(request)

        assert "X-Correlation-ID" in response
        # Should be same as what was attached to request
        assert response["X-Correlation-ID"] == request.correlation_id


@pytest.mark.django_db
class TestCorrelationIDIntegration:
    """Integration tests for correlation ID with Django test client."""

    def test_api_health_returns_correlation_id(self):
        """API health endpoint includes X-Correlation-ID in response."""
        client = Client()
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert "X-Correlation-ID" in response
        assert UUID_PATTERN.match(response["X-Correlation-ID"])

    def test_api_uses_provided_correlation_id(self):
        """API uses correlation ID from request header."""
        client = Client()
        custom_id = str(uuid.uuid4())

        response = client.get(
            "/api/v1/health",
            HTTP_X_CORRELATION_ID=custom_id,
        )

        assert response.status_code == 200
        assert response["X-Correlation-ID"] == custom_id

    def test_correlation_id_persists_across_request(self):
        """Same correlation ID is used throughout request lifecycle."""
        client = Client()
        custom_id = "test-correlation-12345"

        response = client.get(
            "/api/v1/health",
            HTTP_X_CORRELATION_ID=custom_id,
        )

        # The middleware should preserve our custom ID
        assert response["X-Correlation-ID"] == custom_id
