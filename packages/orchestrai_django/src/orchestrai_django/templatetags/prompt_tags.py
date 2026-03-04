# orchestrai_django/templatetags/prompt_tags.py
"""
Template tag for rendering prompts (deprecated).

The PromptSection/PromptEngine system has been replaced by the instruction
system. This template tag is retained as a no-op stub for backward
compatibility with templates that may still reference it.
"""

from typing import Optional
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(name="prompt")
def render_prompt_tag(
    key: str,
    simulation: Optional[object] = None,
    namespace: Optional[str] = None,
) -> str:
    """Deprecated prompt template tag — always returns empty string."""
    return mark_safe("")
