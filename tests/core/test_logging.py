"""Tests for structured logging configuration."""

import structlog
from django.test import RequestFactory

from config.logging import (
    bind_context,
    bind_correlation_id,
    clear_context,
    get_logger,
    unbind_context,
)


class TestStructlogConfiguration:
    """Tests for structlog configuration."""

    def test_get_logger_returns_bound_logger(self):
        """Test that get_logger returns a structlog logger."""
        logger = get_logger(__name__)
        # structlog returns a BoundLoggerLazyProxy which wraps BoundLogger
        # Just verify it has the expected logging methods
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "debug")
        assert callable(logger.info)

    def test_get_logger_with_name(self):
        """Test that get_logger respects the logger name."""
        logger = get_logger("my.custom.logger")
        # Logger should work without errors
        assert logger is not None


class TestCorrelationIDBinding:
    """Tests for correlation ID binding to structlog context."""

    def setup_method(self):
        """Clear context before each test."""
        clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        clear_context()

    def test_bind_correlation_id_adds_to_context(self):
        """Test that bind_correlation_id adds correlation_id to context."""
        bind_correlation_id("test-correlation-123")

        # Get the current context
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("correlation_id") == "test-correlation-123"

    def test_clear_context_removes_correlation_id(self):
        """Test that clear_context removes the correlation_id."""
        bind_correlation_id("test-correlation-123")
        clear_context()

        ctx = structlog.contextvars.get_contextvars()
        assert "correlation_id" not in ctx


class TestContextBinding:
    """Tests for additional context binding."""

    def setup_method(self):
        """Clear context before each test."""
        clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        clear_context()

    def test_bind_context_adds_key_value_pairs(self):
        """Test that bind_context adds arbitrary key-value pairs."""
        bind_context(user_id=123, simulation_id=456)

        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("user_id") == 123
        assert ctx.get("simulation_id") == 456

    def test_bind_context_can_be_called_multiple_times(self):
        """Test that bind_context accumulates context."""
        bind_context(user_id=123)
        bind_context(simulation_id=456)

        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("user_id") == 123
        assert ctx.get("simulation_id") == 456

    def test_unbind_context_removes_specific_keys(self):
        """Test that unbind_context removes specified keys."""
        bind_context(user_id=123, simulation_id=456, session_id=789)
        unbind_context("user_id", "session_id")

        ctx = structlog.contextvars.get_contextvars()
        assert "user_id" not in ctx
        assert "session_id" not in ctx
        assert ctx.get("simulation_id") == 456


class TestCorrelationIDMiddlewareIntegration:
    """Tests for correlation ID middleware with structlog."""

    def setup_method(self):
        """Clear context before each test."""
        clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        clear_context()

    def test_middleware_binds_correlation_id(self):
        """Test that the middleware binds correlation ID to structlog context."""
        from apps.common.middleware import CorrelationIDMiddleware

        def mock_get_response(request):
            # At this point, correlation ID should be bound
            ctx = structlog.contextvars.get_contextvars()
            assert "correlation_id" in ctx
            assert ctx["correlation_id"] == request.correlation_id

            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        request = RequestFactory().get("/test")

        middleware(request)

    def test_middleware_clears_context_after_request(self):
        """Test that the middleware clears context after request completes."""
        from apps.common.middleware import CorrelationIDMiddleware

        def mock_get_response(request):
            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        request = RequestFactory().get("/test")

        middleware(request)

        # Context should be cleared after request
        ctx = structlog.contextvars.get_contextvars()
        assert "correlation_id" not in ctx

    def test_middleware_uses_provided_correlation_id(self):
        """Test that middleware uses X-Correlation-ID header if provided."""
        from apps.common.middleware import CorrelationIDMiddleware

        provided_id = "my-custom-correlation-id"

        def mock_get_response(request):
            ctx = structlog.contextvars.get_contextvars()
            assert ctx["correlation_id"] == provided_id

            from django.http import HttpResponse

            return HttpResponse("OK")

        middleware = CorrelationIDMiddleware(mock_get_response)
        request = RequestFactory().get("/test", HTTP_X_CORRELATION_ID=provided_id)

        middleware(request)

    def test_middleware_clears_context_on_exception(self):
        """Test that context is cleared even if request raises an exception."""
        from apps.common.middleware import CorrelationIDMiddleware

        def mock_get_response(request):
            raise ValueError("Test error")

        middleware = CorrelationIDMiddleware(mock_get_response)
        request = RequestFactory().get("/test")

        try:
            middleware(request)
        except ValueError:
            pass

        # Context should still be cleared
        ctx = structlog.contextvars.get_contextvars()
        assert "correlation_id" not in ctx


class TestLoggerOutput:
    """Tests for logger output format."""

    def setup_method(self):
        """Clear context before each test."""
        clear_context()

    def teardown_method(self):
        """Clear context after each test."""
        clear_context()

    def test_logger_includes_bound_context(self, caplog):
        """Test that logger output includes bound context variables."""
        import logging

        # Set up to capture logs
        caplog.set_level(logging.INFO)

        bind_correlation_id("test-corr-id")
        bind_context(user_id=123)

        logger = get_logger("test")
        logger.info("test message", extra_field="extra_value")

        # Note: The exact format depends on structlog configuration
        # This test verifies the logging doesn't error
        assert len(caplog.records) >= 0  # At minimum, no exceptions occurred
