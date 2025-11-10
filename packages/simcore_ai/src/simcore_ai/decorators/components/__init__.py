# simcore_ai/decorators/components/__init__.py
from .codec_decorator import CodecDecorator
from .prompt_section_decorator import PromptSectionDecorator
from .schema_decorator import SchemaDecorator
from .service_decorator import ServiceDecorator

codec = CodecDecorator()
service = ServiceDecorator()
schema = SchemaDecorator()
prompt_section = PromptSectionDecorator()

__all__ = ["codec", "service", "schema", "prompt_section"]
