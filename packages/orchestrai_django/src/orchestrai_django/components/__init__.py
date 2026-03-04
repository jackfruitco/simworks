"""Lazy exports for orchestrai_django component helpers."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DjangoBaseCodec",
    "DjangoBaseOutputBlock",
    "DjangoBaseOutputItem",
    "DjangoBaseOutputSchema",
    "DjangoBaseService",
    "Prompt",
    "PromptEngine",
    "PromptScenario",
    "PromptSection",
]


_EXPORTS = {
    "DjangoBaseCodec": ("orchestrai_django.components.codecs", "DjangoBaseCodec"),
    "DjangoBaseOutputBlock": ("orchestrai_django.components.schemas", "DjangoBaseOutputBlock"),
    "DjangoBaseOutputItem": ("orchestrai_django.components.schemas", "DjangoBaseOutputItem"),
    "DjangoBaseOutputSchema": ("orchestrai_django.components.schemas", "DjangoBaseOutputSchema"),
    "DjangoBaseService": ("orchestrai_django.components.services", "DjangoBaseService"),
    "Prompt": ("orchestrai_django.components.promptkit", "Prompt"),
    "PromptEngine": ("orchestrai_django.components.promptkit", "PromptEngine"),
    "PromptScenario": ("orchestrai_django.components.promptkit", "PromptScenario"),
    "PromptSection": ("orchestrai_django.components.promptkit", "PromptSection"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)
