"""
Django Tasks backend that executes tasks in daemon threads (fire-and-forget).

This backend provides async execution without requiring external worker processes.
Tasks are executed in background daemon threads after the current database transaction
commits, ensuring database consistency.
"""

import logging
import threading
import uuid
from typing import Any

from asgiref.sync import async_to_sync
from django.db import transaction
from django.tasks.backends.base import BaseTaskBackend
from django.tasks.base import TaskResult, TaskResultStatus, TaskError
from django.tasks.exceptions import TaskResultDoesNotExist
from django.utils import timezone
import traceback as _traceback

logger = logging.getLogger(__name__)


class AsyncThreadBackend(BaseTaskBackend):
    """
    Django Tasks backend that runs tasks in daemon threads (fire-and-forget).

    Features:
    - Fire-and-forget execution (non-blocking enqueue)
    - Transaction-safe (waits for commit before execution)
    - OrchestrAI app context propagation to background threads
    - Supports async task functions
    - Results stored in memory (limited get_result support)
    """

    supports_defer = False  # No scheduling support yet
    supports_async_task = True  # Can run async functions
    supports_get_result = True  # Results stored in memory
    supports_priority = False  # No priority queue

    def __init__(self, alias, params):
        super().__init__(alias, params)
        self._results = {}  # In-memory result storage
        self._results_lock = threading.Lock()

    def enqueue(self, task, args, kwargs):
        """
        Enqueue task for fire-and-forget execution in daemon thread.

        Args:
            task: Django Task object with func, queue_name, etc.
            args: Positional arguments for the task function
            kwargs: Keyword arguments for the task function

        Returns:
            TaskResult with unique ID
        """
        result_id = str(uuid.uuid4())
        enqueued_at = timezone.now()

        # Initialize in-memory READY record so get_result works immediately
        self._update_result(
            task=task,
            result_id=result_id,
            status=TaskResultStatus.READY,
            args=args,
            kwargs=kwargs,
            enqueued_at=enqueued_at,
        )

        # Capture OrchestrAI app context from parent thread
        parent_app = None
        try:
            from orchestrai import get_current_app
            parent_app = get_current_app()
        except Exception:
            logger.debug("No OrchestrAI app context to propagate to background thread")

        def _runner():
            """Execute task in background thread with proper context."""
            try:
                # Restore OrchestrAI app context in this thread
                if parent_app is not None:
                    try:
                        from orchestrai._state import set_current_app
                        from orchestrai.registry.active_app import set_active_registry_app

                        set_current_app(parent_app)
                        set_active_registry_app(parent_app)
                        logger.debug(
                            "AsyncThreadBackend: Restored OrchestrAI app context in background thread for task %s",
                            result_id
                        )
                    except Exception:
                        logger.debug(
                            "AsyncThreadBackend: Failed to bind parent app into background thread",
                            exc_info=True
                        )

                started_at = timezone.now()
                self._update_result(
                    task=task,
                    result_id=result_id,
                    status=TaskResultStatus.RUNNING,
                    args=args,
                    kwargs=kwargs,
                    enqueued_at=enqueued_at,
                    started_at=started_at,
                )

                # Execute the task function
                result_value = self._execute_task(task, args, kwargs)

                finished_at = timezone.now()
                self._update_result(
                    task=task,
                    result_id=result_id,
                    status=TaskResultStatus.SUCCESSFUL,
                    args=args,
                    kwargs=kwargs,
                    enqueued_at=enqueued_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    return_value=result_value,
                )

                logger.debug("AsyncThreadBackend: Task %s completed successfully", result_id)

            except Exception as exc:
                finished_at = timezone.now()
                self._update_result(
                    task=task,
                    result_id=result_id,
                    status=TaskResultStatus.FAILED,
                    args=args,
                    kwargs=kwargs,
                    enqueued_at=enqueued_at,
                    started_at=started_at,
                    finished_at=finished_at,
                    error=exc,
                )

                logger.exception(
                    "AsyncThreadBackend: Task %s failed with error: %s",
                    result_id,
                    str(exc)
                )

        def _start_thread():
            """Start the daemon thread."""
            thread = threading.Thread(
                target=_runner,
                name=f"django-task-{result_id[:8]}",
                daemon=True
            )
            thread.start()
            logger.debug(
                "AsyncThreadBackend: Started daemon thread %s for task %s",
                thread.name,
                result_id
            )

        # Schedule thread to start after transaction commits
        # This ensures database records are committed before background execution
        try:
            transaction.on_commit(_start_thread)
            logger.debug(
                "AsyncThreadBackend: Scheduled task %s to run after transaction commit",
                result_id
            )
        except Exception:
            # Not in a transaction context, start immediately
            _start_thread()
            logger.debug(
                "AsyncThreadBackend: Started task %s immediately (no transaction)",
                result_id
            )

        # Return TaskResult immediately (fire-and-forget)
        result = TaskResult(
            task=task,
            id=result_id,
            status=TaskResultStatus.READY,
            enqueued_at=enqueued_at,
            started_at=None,
            finished_at=None,
            last_attempted_at=None,
            args=list(args),
            kwargs=dict(kwargs),
            backend=getattr(task, "backend", self.alias),
            errors=[],
            worker_ids=[],
        )
        return result

    def _execute_task(self, task, args, kwargs):
        """
        Execute the task function (sync or async).

        Args:
            task: Django Task object
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            The task function's return value
        """
        from inspect import iscoroutinefunction

        func = task.func

        if iscoroutinefunction(func):
            # Async function - run with async_to_sync
            return async_to_sync(func)(*args, **kwargs)
        else:
            # Sync function - run directly
            return func(*args, **kwargs)

    def _update_result(
        self,
        *,
        task,
        result_id: str,
        status: str,
        args: tuple,
        kwargs: dict,
        enqueued_at,
        started_at=None,
        finished_at=None,
        return_value: Any = None,
        error: BaseException | None = None,
    ) -> None:
        """Update task result in memory with the fields expected by Django Tasks."""
        error_items: list[TaskError] = []
        if error is not None:
            error_items = [
                TaskError(
                    exception_class_path=f"{error.__class__.__module__}.{error.__class__.__qualname__}",
                    traceback="".join(_traceback.format_exception(type(error), error, error.__traceback__)),
                )
            ]

        with self._results_lock:
            self._results[result_id] = {
                "task": task,
                "status": status,
                "args": list(args),
                "kwargs": dict(kwargs),
                "backend": getattr(task, "backend", self.alias),
                "enqueued_at": enqueued_at,
                "started_at": started_at,
                "finished_at": finished_at,
                "last_attempted_at": finished_at or started_at,
                "errors": error_items,
                "worker_ids": [],
                "return_value": return_value,
            }

    def get_result(self, result_id: str) -> TaskResult:
        """
        Retrieve a task result by ID.

        Args:
            result_id: The task result ID

        Returns:
            TaskResult with status and return_value/error

        Raises:
            TaskResultDoesNotExist: If result not found
        """
        with self._results_lock:
            if result_id not in self._results:
                raise TaskResultDoesNotExist(f"No result found for task {result_id}")

            data = self._results[result_id]

        result = TaskResult(
            task=data["task"],
            id=result_id,
            status=data["status"],
            enqueued_at=data.get("enqueued_at"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            last_attempted_at=data.get("last_attempted_at"),
            args=data.get("args", []),
            kwargs=data.get("kwargs", {}),
            backend=data.get("backend", self.alias),
            errors=data.get("errors", []),
            worker_ids=data.get("worker_ids", []),
        )

        if data.get("status") == TaskResultStatus.SUCCESSFUL:
            object.__setattr__(result, "_return_value", data.get("return_value"))

        return result

    def clear_results(self):
        """Clear all stored results (for testing/cleanup)."""
        with self._results_lock:
            self._results.clear()
