# simcore_ai/decorators/components/__init__.py
from .codec_decorator import DjangoCodecDecorator
from .prompt_section_decorator import DjangoPromptSectionDecorator
from .schema_decorator import DjangoSchemaDecorator
from .service_decorator import DjangoServiceDecorator

codec = DjangoCodecDecorator()
service = DjangoServiceDecorator()
schema = DjangoSchemaDecorator()
prompt_section = DjangoPromptSectionDecorator()

__all__ = ["codec", "service", "schema", "prompt_section"]
