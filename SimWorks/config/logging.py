"""
Logging Configuration for SimWorks

This module defines the logging configuration for the Django project. It sets a global log level using the DJANGO_LOG_LEVEL environment variable (defaulting to 'INFO') and allows for module-specific overrides using environment variables such as CHATLAB_LOG_LEVEL, ACCOUNTS_LOG_LEVEL, NOTIFY_LOG_LEVEL, and AI_LOG_LEVEL.

The LOGGING dictionary configures formatters, handlers, and loggers for various parts of the application, ensuring that log messages are routed appropriately. The console handler outputs log messages to the standard output using a verbose format that includes the timestamp, log level, logger name, and line number.

Usage:
  - Import this module in the Django settings to provide a centralized and customizable logging configuration.
  - Adjust environment variables to change logging levels without modifying code.

"""

from core.utils.system import check_env

LOG_LEVEL = check_env("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "()": "core.utils.AppColorFormatter",
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
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "py.warnings": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "core": {
            "handlers": ["console"],
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
        "simai": {
            "handlers": ["console"],
            "level": check_env("SIMAI_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "simai.prompts": {
            "handlers": ["console"],
            "level": check_env("SIMAI_PROMPTS_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "simai.parser": {
            "handlers": ["console"],
            "level": check_env("SIMAI_PARSER_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
        "simcore": {
            "handlers": ["console"],
            "level": check_env("SIMCORE_LOG_LEVEL", None) or LOG_LEVEL,
            "propagate": False,
        },
    },
}
