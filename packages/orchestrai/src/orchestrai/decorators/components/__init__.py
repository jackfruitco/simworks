# orchestrai/decorators/components/__init__.py
from .service_decorator import ServiceDecorator

service = ServiceDecorator()
__all__ = ["service"]
