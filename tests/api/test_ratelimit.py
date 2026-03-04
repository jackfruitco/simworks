"""Tests for rate limiting functionality."""

import time
from unittest.mock import MagicMock, patch

from django.test import RequestFactory
import pytest

from apps.common.ratelimit import (
    RateLimitExceeded,
    check_rate_limit,
    get_client_ip,
    get_rate_limit_key,
    rate_limit,
)


class TestGetClientIP:
    """Tests for client IP extraction."""

    def test_returns_remote_addr_when_no_forwarded_header(self):
        """Test that REMOTE_ADDR is used when X-Forwarded-For is absent."""
        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        ip = get_client_ip(request)
        assert ip == "192.168.1.1"

    def test_returns_first_forwarded_ip(self):
        """Test that the first IP in X-Forwarded-For chain is used."""
        request = RequestFactory().get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1, 192.168.1.1, 127.0.0.1"

        ip = get_client_ip(request)
        assert ip == "10.0.0.1"

    def test_returns_unknown_when_no_ip_available(self):
        """Test fallback to 'unknown' when no IP info available."""
        request = RequestFactory().get("/")
        # Remove REMOTE_ADDR if present
        request.META.pop("REMOTE_ADDR", None)

        ip = get_client_ip(request)
        assert ip == "unknown"


class TestGetRateLimitKey:
    """Tests for rate limit key generation."""

    def test_ip_key_includes_hashed_ip(self):
        """Test that IP-based key includes a hashed IP."""
        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        key = get_rate_limit_key(request, "ip", "test")
        assert key.startswith("ratelimit:test:ip:")
        # IP should be hashed, not plain
        assert "192.168.1.1" not in key

    def test_user_key_includes_user_id_when_authenticated(self):
        """Test that user-based key includes user ID for authenticated users."""
        request = RequestFactory().get("/")
        request.user = MagicMock(is_authenticated=True, pk=123)

        key = get_rate_limit_key(request, "user", "test")
        assert "user:123" in key

    def test_user_key_falls_back_to_ip_when_unauthenticated(self):
        """Test that user-based key falls back to IP for anonymous users."""
        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"
        request.user = MagicMock(is_authenticated=False)

        key = get_rate_limit_key(request, "user", "test")
        assert "ip:" in key
        assert "user:" not in key

    def test_ip_user_key_includes_both(self):
        """Test that ip_user key includes both IP and user."""
        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"
        request.user = MagicMock(is_authenticated=True, pk=123)

        key = get_rate_limit_key(request, "ip_user", "test")
        assert "ip:" in key
        assert "user:123" in key


class TestCheckRateLimit:
    """Tests for the rate limit check function."""

    def test_allows_request_within_limit(self):
        """Test that requests within the limit are allowed."""
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value.__enter__ = lambda s: s
        mock_redis.pipeline.return_value.__exit__ = lambda s, *args: None
        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.return_value = [None, 0, None, None]  # zcard returns 0

        is_allowed, count, retry_after = check_rate_limit(
            mock_redis, "test:key", limit=10, period=60
        )

        assert is_allowed is True
        assert count == 1
        assert retry_after == 0

    def test_blocks_request_exceeding_limit(self):
        """Test that requests exceeding the limit are blocked."""
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value.__enter__ = lambda s: s
        mock_redis.pipeline.return_value.__exit__ = lambda s, *args: None
        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.return_value = [None, 10, None, None]  # zcard returns 10 (at limit)

        # Mock zrange for getting oldest entry
        mock_redis.zrange.return_value = [(b"12345:123", time.time() - 30)]

        is_allowed, count, retry_after = check_rate_limit(
            mock_redis, "test:key", limit=10, period=60
        )

        assert is_allowed is False
        assert count == 10
        assert retry_after > 0


class TestRateLimitDecorator:
    """Tests for the rate_limit decorator."""

    def test_decorator_stores_config(self):
        """Test that the decorator stores rate limit config on the function."""

        @rate_limit(key="ip", limit=5, period=60, prefix="test")
        def my_endpoint(request):
            return "ok"

        assert hasattr(my_endpoint, "_rate_limit_config")
        assert my_endpoint._rate_limit_config["key"] == "ip"
        assert my_endpoint._rate_limit_config["limit"] == 5
        assert my_endpoint._rate_limit_config["period"] == 60
        assert my_endpoint._rate_limit_config["prefix"] == "test"

    def test_allows_request_when_redis_unavailable(self):
        """Test that requests are allowed when Redis is unavailable (fail open)."""
        with patch("apps.common.ratelimit.get_redis_client", return_value=None):

            @rate_limit(key="ip", limit=1, period=60)
            def my_endpoint(request):
                return "ok"

            request = RequestFactory().get("/")
            result = my_endpoint(request)
            assert result == "ok"

    def test_raises_rate_limit_exceeded(self):
        """Test that RateLimitExceeded is raised when limit is exceeded."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.pipeline.return_value.__enter__ = lambda s: s
        mock_redis.pipeline.return_value.__exit__ = lambda s, *args: None
        mock_pipe = mock_redis.pipeline.return_value
        mock_pipe.execute.return_value = [None, 5, None, None]  # At limit
        mock_redis.zrange.return_value = [(b"12345:123", time.time() - 30)]

        with patch("apps.common.ratelimit.get_redis_client", return_value=mock_redis):

            @rate_limit(key="ip", limit=5, period=60)
            def my_endpoint(request):
                return "ok"

            request = RequestFactory().get("/")
            request.META["REMOTE_ADDR"] = "192.168.1.1"

            with pytest.raises(RateLimitExceeded) as exc_info:
                my_endpoint(request)

            assert exc_info.value.status_code == 429
            assert exc_info.value.retry_after > 0


class TestRateLimitExceeded:
    """Tests for RateLimitExceeded exception."""

    def test_exception_has_correct_status_code(self):
        """Test that the exception has a 429 status code."""
        exc = RateLimitExceeded(retry_after=30)
        assert exc.status_code == 429

    def test_exception_has_retry_after(self):
        """Test that the exception includes retry_after value."""
        exc = RateLimitExceeded(retry_after=30)
        assert exc.retry_after == 30


@pytest.mark.django_db
class TestRateLimitAPIIntegration:
    """Integration tests for rate limiting on API endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        from django.test import Client

        return Client()

    def test_auth_endpoint_has_rate_limit_config(self):
        """Test that auth endpoints have rate limit configuration."""
        from api.v1.endpoints.auth import obtain_token, refresh_token

        assert hasattr(obtain_token, "_rate_limit_config")
        assert obtain_token._rate_limit_config["limit"] == 5
        assert obtain_token._rate_limit_config["period"] == 60

        assert hasattr(refresh_token, "_rate_limit_config")
        assert refresh_token._rate_limit_config["limit"] == 5

    def test_message_endpoint_has_rate_limit_config(self):
        """Test that message endpoints have rate limit configuration."""
        from api.v1.endpoints.messages import create_message, get_message, list_messages

        assert hasattr(create_message, "_rate_limit_config")
        assert create_message._rate_limit_config["limit"] == 30  # message limit

        assert hasattr(list_messages, "_rate_limit_config")
        assert list_messages._rate_limit_config["limit"] == 100  # api limit

        assert hasattr(get_message, "_rate_limit_config")
        assert get_message._rate_limit_config["limit"] == 100  # api limit

    def test_simulation_endpoints_have_rate_limit_config(self):
        """Test that simulation endpoints have rate limit configuration."""
        from api.v1.endpoints.simulations import (
            create_simulation,
            end_simulation,
            get_simulation,
            list_simulations,
        )

        for endpoint in [list_simulations, get_simulation, create_simulation, end_simulation]:
            assert hasattr(endpoint, "_rate_limit_config")
            assert endpoint._rate_limit_config["limit"] == 100

    def test_modifiers_endpoint_has_rate_limit_config(self):
        """Test that modifiers endpoint has rate limit configuration."""
        from api.v1.endpoints.modifiers import list_modifier_groups

        assert hasattr(list_modifier_groups, "_rate_limit_config")
        assert list_modifier_groups._rate_limit_config["limit"] == 100
        assert list_modifier_groups._rate_limit_config["key"] == "ip"

    def test_rate_limit_error_response_format(self, client):
        """Test that rate limit errors return the correct response format."""
        # This test verifies the exception handler is registered correctly
        # We can't easily trigger a real rate limit in tests without Redis,
        # but we can verify the error response schema is defined

        from api.v1.api import api

        # Check that RateLimitExceeded handler is registered
        assert RateLimitExceeded in api._exception_handlers

    def test_health_endpoint_not_rate_limited(self, client):
        """Test that health endpoint works without rate limiting."""
        # Health check should always work even under load
        response = client.get("/api/v1/health")
        assert response.status_code == 200
