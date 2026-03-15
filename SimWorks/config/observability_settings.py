"""Observability and instrumentation settings."""

from __future__ import annotations

import os

import logfire

logfire_token = os.getenv("LOGFIRE_API_KEY")
if logfire_token:
    logfire.configure(token=logfire_token)
else:
    # Allow local/test environments to run without Logfire authentication.
    # console=False suppresses the local OTel console exporter that would otherwise
    # duplicate every log line already printed by the Django console handler.
    logfire.configure(send_to_logfire=False, console=False)

logfire.instrument_httpx(
    capture_all=True
    # capture_response_body=True,
    # capture_request_body=True,
    # capture_headers=True,
)
logfire.instrument_django(excluded_urls="/health(?:/|$)")
logfire.instrument_openai(suppress_other_instrumentation=False)
