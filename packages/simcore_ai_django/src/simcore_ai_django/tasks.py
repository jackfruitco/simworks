# simcore_ai_django/tasks.py
"""
Celery-based task entrypoints for simcore_ai_django have been removed.

The legacy `run_service_task` and its dependency on a Celery queue are no
longer supported in AIv3. Execution is now handled exclusively via Django
6.0 Tasks, with one Task auto-registered per service class and exposed as:

    MyService.task

To enqueue work, call:

    MyService.task.enqueue(...)

and rely on the configured Django TASKS backend (ImmediateBackend for now)
instead of Celery's @shared_task entrypoints.
"""


__all__: list[str] = []