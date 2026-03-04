"""
Logging Configuration for SimWorks

This module defines the logging configuration for the Django project. It sets a global log level using the DJANGO_LOG_LEVEL environment variable (defaulting to 'INFO') and allows for module-specific overrides using environment variables such as CHATLAB_LOG_LEVEL, ACCOUNTS_LOG_LEVEL, NOTIFY_LOG_LEVEL, and AI_LOG_LEVEL.

The LOGGING dictionary configures formatters, handlers, and loggers for various parts of the application, ensuring that log input are routed appropriately. The console handler output log input to the standard output using a verbose format that includes the timestamp, log level, logger name, and line number.

Structlog Integration:
  - Use get_logger() for structured logging with automatic correlation ID inclusion
  - Use bind_correlation_id() in middleware to set correlation ID for the request
  - Use bind_context() to add request-scoped context (user_id, simulation_id, etc.)

Usage:
  - Import this module in the Django settings to provide a centralized and customizable logging configuration.
  - Adjust environment variables to change logging levels without modifying code.

"""

from typing import Any

import structlog

from apps.common.utils.system import check_env

LOG_LEVEL = check_env("DJANGO_LOG_LEVEL", "INFO").upper()
LOGFIRE_LOG_LEVEL = check_env("LOGFIRE_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "()": "apps.common.utils.AppColorFormatter",
            "format": "[{asctime}] {levelname} [{name}:{lineno}] {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "logfire": {"class": "logfire.LogfireLoggingHandler", "level": LOGFIRE_LOG_LEVEL},
    },
    "root": {
        "handlers": ["console", "logfire"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "py.warnings": {
            "handlers": ["console", "logfire"],
            "level": "WARNING",
            "propagate": False,
        },
        "core": {
            "handlers": ["console", "logfire"],
            "level": check_env("CORE_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "core.utils.formatters": {
            "handlers": ["console"],
            "level": check_env("CORE_FORMATTER_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "chatlab": {
            "handlers": ["console"],
            "level": check_env("CHATLAB_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "accounts": {
            "handlers": ["console"],
            "level": check_env("ACCOUNTS_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "notifications": {
            "handlers": ["console"],
            "level": check_env("NOTIFY_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "simulation": {
            "handlers": ["console", "logfire"],
            "level": check_env("SIMULATION_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        # ---------- AI loggers -------------------------------------------------------------------
        "orchestrai": {
            "handlers": ["console", "logfire"],
            "level": check_env("AI_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "orchestrai_django": {
            "handlers": ["console", "logfire"],
            "level": check_env("AI_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "api": {
            "handlers": ["console", "logfire"],
            "level": check_env("API_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
    },
}


# =============================================================================
# Structlog Configuration
# =============================================================================


def _add_app_context(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add application context to log entries."""
    event_dict.setdefault("app", "simworks")
    return event_dict


def configure_structlog() -> None:
    """Configure structlog for the application.

    This configures structlog to work alongside Django's standard logging,
    with automatic correlation ID inclusion via contextvars.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            _add_app_context,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger instance.

    This returns a structured logger that automatically includes:
    - Correlation ID (if bound via middleware)
    - Any other context bound via bind_context()
    - Timestamp, log level, and logger name

    Args:
        name: Logger name (usually __name__). If None, returns the root logger.

    Returns:
        A bound structlog logger instance.

    Example:
        logger = get_logger(__name__)
        logger.info("User logged in", user_id=123, action="login")
    """
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str) -> None:
    """Bind correlation ID to the current context.

    This should be called from middleware at the start of each request.
    The correlation ID will be automatically included in all log entries
    for the duration of the request.

    Args:
        correlation_id: The correlation ID to bind.
    """
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def bind_context(**kwargs: Any) -> None:
    """Bind additional context variables for the current request.

    Use this to add request-scoped context that should appear in all
    log entries for the current request.

    Args:
        **kwargs: Key-value pairs to bind to the logging context.

    Example:
        bind_context(user_id=123, simulation_id=456)
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all bound context variables.

    This should be called at the end of each request to prevent
    context leakage between requests.
    """
    structlog.contextvars.clear_contextvars()


def unbind_context(*keys: str) -> None:
    """Unbind specific context variables.

    Args:
        *keys: Keys to remove from the context.

    Example:
        unbind_context("user_id", "simulation_id")
    """
    structlog.contextvars.unbind_contextvars(*keys)


# Configure structlog on module import
configure_structlog()
