# simcore_ai_django/components/services/mixins.py
from __future__ import annotations

"""
Legacy execution mixins for Django services have been removed.

The old `ServiceExecutionMixin` and its dependency on
`simcore_ai_django.execution.entrypoint` are no longer supported in AIv3.

Execution is now handled exclusively via Django Tasks. Use:

    MyService.task.enqueue(...)

for asynchronous dispatch, and rely on the configured Django TASKS backend
(ImmediateBackend for now) instead of the old execution backends.
"""

__all__: list[str] = []
