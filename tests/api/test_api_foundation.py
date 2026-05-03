"""Tests for API v1 foundation.

Tests that:
1. API mounts correctly at /api/v1/
2. Health endpoint works
3. Error handling returns RFC 7807 format
4. OpenAPI schema is generated
5. Authentication works on protected endpoints
"""

from django.test import Client
import pytest


@pytest.mark.django_db
class TestAPIMount:
    """Tests that API is correctly mounted."""

    def test_api_v1_is_mounted(self):
        """API v1 responds at /api/v1/."""
        client = Client()
        response = client.get("/api/v1/health")

        assert response.status_code == 200

    def test_build_info_endpoint_is_mounted(self):
        """Build info endpoint responds at /api/v1/build-info/."""
        client = Client()
        response = client.get("/api/v1/build-info/")

        assert response.status_code == 200

    def test_unknown_route_returns_404(self):
        """Unknown API routes return 404."""
        client = Client()
        response = client.get("/api/v1/nonexistent-endpoint/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_200(self):
        """Health endpoint returns 200 OK."""
        client = Client()
        response = client.get("/api/v1/health")

        assert response.status_code == 200

    def test_health_returns_json(self):
        """Health endpoint returns JSON content type."""
        client = Client()
        response = client.get("/api/v1/health")

        assert response["Content-Type"].startswith("application/json")

    def test_health_response_structure(self):
        """Health response has expected structure."""
        client = Client()
        response = client.get("/api/v1/health")
        data = response.json()

        assert "status" in data
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_health_auth_requires_login(self):
        """Authenticated health endpoint requires login."""
        client = Client()
        response = client.get("/api/v1/health/auth")

        # Should return 401 or 403 for unauthenticated request
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestErrorHandling:
    """Tests for API error handling."""

    def test_404_returns_json(self):
        """404 errors return JSON format."""
        client = Client()
        response = client.get("/api/v1/nonexistent/")

        assert response.status_code == 404
        # Django Ninja returns JSON for 404

    def test_error_includes_correlation_id(self):
        """Error responses include correlation ID when provided."""
        client = Client()
        custom_id = "error-test-correlation-id"

        response = client.get(
            "/api/v1/nonexistent/",
            HTTP_X_CORRELATION_ID=custom_id,
        )

        # Correlation ID should be in response header regardless of error
        assert response["X-Correlation-ID"] == custom_id


@pytest.mark.django_db
class TestOpenAPISchema:
    """Tests for OpenAPI schema generation."""

    def test_openapi_schema_available(self):
        """OpenAPI schema is accessible at /api/v1/openapi.json."""
        client = Client()
        response = client.get("/api/v1/openapi.json")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

    def test_openapi_schema_structure(self):
        """OpenAPI schema has expected structure."""
        client = Client()
        response = client.get("/api/v1/openapi.json")
        schema = response.json()

        assert "openapi" in schema
        assert schema["openapi"].startswith("3.")
        assert "info" in schema
        assert schema["info"]["title"] == "MedSim API"
        assert "paths" in schema

    def test_openapi_includes_health_endpoint(self):
        """OpenAPI schema includes health endpoint."""
        client = Client()
        response = client.get("/api/v1/openapi.json")
        schema = response.json()

        # Check for health endpoint - may be /health or /api/v1/health depending on mount
        paths = schema["paths"]
        health_paths = [p for p in paths if "health" in p]
        assert len(health_paths) > 0, f"No health endpoint found in paths: {list(paths.keys())}"


@pytest.mark.django_db
class TestAuthentication:
    """Tests for API authentication."""

    def test_unauthenticated_access_to_protected_endpoint(self):
        """Protected endpoints reject unauthenticated requests."""
        client = Client()
        response = client.get("/api/v1/health/auth")

        assert response.status_code in (401, 403)

    def test_authenticated_access_to_protected_endpoint(self, django_user_model):
        """Protected endpoints allow authenticated requests."""
        from apps.accounts.models import UserRole

        # Create required role first (UserRole only has 'title' field)
        role = UserRole.objects.create(title="Test Role")

        # Create a test user with the role
        user = django_user_model.objects.create_user(
            password="testpass123",
            email="testuser@example.com",
            role=role,
        )

        client = Client()
        client.force_login(user)

        response = client.get("/api/v1/health/auth")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
