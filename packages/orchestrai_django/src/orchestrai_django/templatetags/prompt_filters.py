# orchestrai_django/prompts/prompt_filters.py
"""
Template filters for prompt rendering.
These can be registered as builtins via Django settings or loaded explicitly in templates.
"""

import json
import textwrap

from django import template

from orchestrai.utils.json import json_default

register = template.Library()


@register.filter
def dedent(value: str) -> str:
    """Remove common leading whitespace and strip trailing whitespace."""
    return textwrap.dedent(value or "").strip()


@register.filter
def tojson(value) -> str:
    """Serialize Python objects to JSON for prompt rendering.

    Handles non-JSON types like UUID, datetime, Decimal via json_default.
    """
    return json.dumps(value, ensure_ascii=False, default=json_default)
