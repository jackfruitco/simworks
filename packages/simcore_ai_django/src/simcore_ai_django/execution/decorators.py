# simcore_ai_django/execution/decorators.py
import logging
from typing import Type, TypeVar

from .registry import register_backend
from .types import BaseExecutionBackend

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Type[BaseExecutionBackend])


def task_backend(name: str):
    """
    Class decorator to register an execution backend under a stable name.

    Usage
    -----
    Basic:
        @task_backend("immediate")
        class ImmediateBackend(BaseExecutionBackend):
            ...

        @task_backend("celery")
        class CeleryBackend(BaseExecutionBackend):
            ...

    Registration timing:
        The decorator registers the backend at *import time*. To ensure it runs,
        the backend module must be imported during app startup. The package
        `simcore_ai_django.execution.__init__` imports the built-in backends via a
        private alias (not exported) so registration happens automatically.

    Notes
    -----
    - The decorated class **must** subclass `BaseExecutionBackend`.
    - Third-party apps can expose custom backends by importing their modules
      from AppConfig.ready() or another initialization hook.
    - Programmatic registration is also available via `register_backend(name, cls)`.
    """

    def _wrap(cls: Type[T]) -> Type[T]:
        if not issubclass(cls, BaseExecutionBackend):
            raise TypeError("@task_backend can only decorate BaseExecutionBackend subclasses")
        register_backend(name, cls)
        logger.debug("Registered execution backend '%s' for '%s'", name, cls)
        return cls

    return _wrap
