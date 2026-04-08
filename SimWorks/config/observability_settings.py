"""Observability and instrumentation settings."""

import os

import logfire

from .settings_parsers import bool_from_env

LOGFIRE_ENABLED = bool_from_env("LOGFIRE_ENABLED", default=True)
HAS_LOGFIRE_TOKEN = bool(os.getenv("LOGFIRE_TOKEN") or os.getenv("LOGFIRE_API_KEY"))

if LOGFIRE_ENABLED and HAS_LOGFIRE_TOKEN:
    logfire.configure()
    logfire.instrument_httpx(
        capture_all=True,
        # capture_response_body=True,
        # capture_request_body=True,
        # capture_headers=True,
    )
    logfire.instrument_django(excluded_urls="/health(?:/|$)")
    logfire.instrument_openai(suppress_other_instrumentation=False)
else:
    logfire.configure(send_to_logfire=False, console=False)
