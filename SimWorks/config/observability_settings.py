"""Observability and instrumentation settings."""

import os

import logfire

if os.getenv("LOGFIRE_TOKEN") or os.getenv("LOGFIRE_API_KEY"):
    logfire.configure()
else:
    logfire.configure(send_to_logfire=False, console=False)

logfire.instrument_httpx(
    capture_all=True
    # capture_response_body=True,
    # capture_request_body=True,
    # capture_headers=True,
)
logfire.instrument_django(excluded_urls="/health(?:/|$)")
logfire.instrument_openai(suppress_other_instrumentation=False)
