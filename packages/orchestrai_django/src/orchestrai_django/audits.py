"""
Audit functions for AIRequestAudit and AIResponseAudit have been removed.

ServiceCall provides sufficient tracking for service execution,
including status, input/output, errors, and retry attempts.

If you need detailed request/response auditing, consider enhancing
ServiceCall with additional fields such as:
- provider_name, client_name, model_name
- token_input, token_output, token_reasoning
- correlation_id for linking related calls
- request_messages and response_outputs JSONFields

See ServiceCall model in models.py for the current implementation.
"""

# This file is intentionally minimal to avoid import errors.
# The write_request_audit() and write_response_audit() functions
# that previously existed here have been removed.
