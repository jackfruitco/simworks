# orchestrai_django/tasks.py
"""
Celery-based task entrypoints for orchestrai_django have been removed.

The legacy `run_service_task` and its dependency on a Celery queue are no
longer supported in AIv3.

Execution should go through the OrchestrAI app instance:

    from orchestrai import get_current_app
    get_current_app().services.schedule(MyService, **context)

Async dispatch is available via ``aschedule``/``astart`` without any Celery or
Django task wrappers.
"""

__all__: list[str] = []
