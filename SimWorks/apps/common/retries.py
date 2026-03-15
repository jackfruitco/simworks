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


def _sim_has_chatlab_session(sim) -> bool:
    """Domain backstop: True if sim has a ChatLab session attached."""
    try:
        _ = sim.chatlab_session
        return True
    except Exception:
        return False


def is_simulation_initial_generation_retryable(sim) -> bool:
    """Return True only when the simulation's initial-generation failure is retryable
    via the shared /retry-initial/ (ChatLab path).

    Rules:
    - chatlab_initial_generation_* → True  (new prefixed ChatLab codes)
    - trainerlab_initial_generation_* → False  (TrainerLab codes, never retryable here)
    - provider_timeout / provider_transient_error → True only if ChatLab-backed
    - legacy initial_generation_* (unprefixed) → True only if ChatLab-backed
    - anything else → False
    """
    reason_code = (getattr(sim, "terminal_reason_code", "") or "")

    if reason_code.startswith("trainerlab_initial_generation"):
        return False

    if reason_code.startswith("chatlab_initial_generation"):
        return True

    # Legacy / generic codes: use domain backstop
    is_legacy = reason_code.startswith("initial_generation") or (
        reason_code in INITIAL_GENERATION_RETRYABLE_REASON_CODES
    )
    if is_legacy:
        return _sim_has_chatlab_session(sim)

    return False
