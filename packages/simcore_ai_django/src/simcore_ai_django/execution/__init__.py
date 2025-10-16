"""simcore_ai_django.execution package.

Provides orchestration and abstraction for executing AI service tasks through a unified backend interface.

Overview
--------
This package defines a consistent framework for dispatching AI service execution
requests across different backends (synchronous or asynchronous). The supported
backends (Immediate, Celery, and future Django Tasks) share a common API through
`BaseExecutionBackend` and are discoverable via a central registry.

Usage
-----
1. **Registration:**
   Use the `@task_backend` decorator to register new backends automatically when
   their modules are imported.

   ```python
   from simcore_ai_django.execution.types import BaseExecutionBackend
   from simcore_ai_django.execution.decorators import task_backend

   @task_backend("immediate")
   class ImmediateBackend(BaseExecutionBackend):
       supports_priority = False

       def execute(self, *, service_cls, kwargs):
           return service_cls(**kwargs).run()
   ```

2. **Backend discovery:**
   The registry maintains all available backends. You can retrieve one by name:

   ```python
   from simcore_ai_django.execution import get_backend_by_name
   backend = get_backend_by_name("celery")
   backend.enqueue(service_cls=MyService, kwargs={"user_id": 123})
   ```

3. **Entrypoint helpers:**
   The `execute()` entrypoint chooses the backend automatically based on service
   defaults, Django settings, or explicit overrides.

   ```python
   from simcore_ai_django.execution.entrypoint import execute
   execute(MyService, user_id=123)
   ```

4. **Built-in backends:**
   - `ImmediateBackend`: Executes tasks synchronously (in-process)
   - `CeleryBackend`: Enqueues tasks to Celery for async execution
   - `DjangoTasksBackend`: Reserved placeholder for Django 6.0 Tasks framework

Implementation Details
----------------------
- Backends are auto-registered at import via `execution.__init__`.
- The module imports built-in backends as a private alias (`_backends`) solely to
  trigger decorator registration.
- Public API exposes only the registry and decorator utilities.

Public API
-----------
    - `register_backend(name, cls)`: Register a backend class manually.
    - `get_backend_by_name(name)`: Retrieve a backend singleton by name.
    - `task_backend(name)`: Decorator for declarative backend registration.
    - `execute(service_cls, **kwargs)`: Execute a service synchronously.
"""
# Import built-in backends as private alias
# Registers backends via decorator but does not expose them
from . import backends as _backends  # noqa: F401
from .decorators import task_backend
from .entrypoint import execute
# Public API re-exports
from .registry import register_backend, get_backend_by_name

__all__ = [
    "register_backend",
    "get_backend_by_name",
    "task_backend",
    "execute",
]
