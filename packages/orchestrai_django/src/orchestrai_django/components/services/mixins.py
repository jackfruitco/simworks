# orchestrai_django/components/services/mixins.py


"""
Legacy execution mixins for Django services have been removed.

The old `ServiceExecutionMixin` and its dependency on
`orchestrai_django.execution.entrypoint` are no longer supported in AIv3.

Execution should go through the core OrchestrAI app:

    from orchestrai import get_current_app
    get_current_app().services.schedule(MyService, **context)

Async workflows can call ``aschedule``/``astart`` instead of Django Tasks.
"""

__all__: list[str] = []
