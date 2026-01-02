"""Deprecated Django Tasks-backed runner shim."""

from ._messages import REMOVED_SERVICE_RUNNER_MESSAGE

raise RuntimeError(REMOVED_SERVICE_RUNNER_MESSAGE)

__all__: list[str] = []
