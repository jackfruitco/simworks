# orchestrai/decorators/components/__init__.py
from .instruction_decorator import InstructionDecorator
from .service_decorator import ServiceDecorator

instruction = InstructionDecorator()
service = ServiceDecorator()
__all__ = ["instruction", "service"]
