"""Framework-neutral task proxy compatibility helpers."""

from __future__ import annotations

from orchestrai.components.services.service import CoreTaskProxy, TaskDescriptor
from orchestrai.components.services.task_proxy import ServiceSpec

DjangoServiceSpec = ServiceSpec
DjangoTaskProxy = CoreTaskProxy
DjangoTaskDescriptor = TaskDescriptor


def use_django_task_proxy() -> None:
    """Compatibility shim retained for older integration code."""

    return None


__all__ = [
    "DjangoServiceSpec",
    "DjangoTaskDescriptor",
    "DjangoTaskProxy",
    "ServiceSpec",
    "use_django_task_proxy",
]
