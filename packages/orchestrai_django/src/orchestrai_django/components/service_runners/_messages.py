"""Shared messaging for removed service runner shims."""

REMOVED_SERVICE_RUNNER_MESSAGE = (
    "Service runners have been removed. Use BaseService.task.run/arun or the Django task proxy."
)

__all__ = ["REMOVED_SERVICE_RUNNER_MESSAGE"]
