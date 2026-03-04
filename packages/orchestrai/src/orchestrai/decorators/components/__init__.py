# orchestrai/decorators/components/__init__.py
from .codec_decorator import CodecDecorator
from .instruction_decorator import InstructionDecorator
from .schema_decorator import SchemaDecorator
from .service_decorator import ServiceDecorator

codec = CodecDecorator()
service = ServiceDecorator()
schema = SchemaDecorator()
instruction = InstructionDecorator()

__all__ = ["codec", "service", "schema", "instruction"]
