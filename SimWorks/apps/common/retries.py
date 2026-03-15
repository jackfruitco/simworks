"""Shared retry policy helpers for user-visible API and event contracts."""

USER_RETRY_LIMIT = 2

INITIAL_GENERATION_RETRYABLE_REASON_CODES = frozenset(
    {"provider_timeout", "provider_transient_error"}
)


def has_user_retries_remaining(retry_count: int) -> bool:
    """Return whether a user can retry again after the current attempt count."""
    return retry_count < USER_RETRY_LIMIT


def is_initial_generation_retryable_reason(reason_code: str | None) -> bool:
    """Return whether a failure reason should expose the initial-generation retry CTA."""
    normalized_reason = reason_code or ""
    return normalized_reason.startswith("initial_generation") or (
        normalized_reason in INITIAL_GENERATION_RETRYABLE_REASON_CODES
    )
