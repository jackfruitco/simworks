from .task_proxy import (
    DjangoServiceSpec,
    DjangoTaskDescriptor,
    DjangoTaskProxy,
    use_django_task_proxy,
)

__all__ = [
    "DjangoServiceSpec",
    "DjangoTaskProxy",
    "DjangoTaskDescriptor",
    "use_django_task_proxy",
]
