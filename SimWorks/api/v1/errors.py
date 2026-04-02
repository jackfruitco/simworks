"""Custom API error types."""

from __future__ import annotations

from typing import Any

from ninja.errors import HttpError


class GuardDeniedError(HttpError):
    """Raised when a guard check denies an action.

    Carries the full structured denial signal so the exception handler
    can include it in the response payload.
    """

    def __init__(self, denial_signal: dict[str, Any]) -> None:
        message = denial_signal.get("message", "Action denied by guard.")
        super().__init__(403, message)
        self.denial_signal = denial_signal
