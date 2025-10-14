# simcore_ai_django/prompts/prompt_filters.py
"""
Template filters for prompt rendering.
These can be registered as builtins via Django settings or loaded explicitly in templates.
"""
from django import template
import textwrap
import json

register = template.Library()

@register.filter
def dedent(value: str) -> str:
  """Remove common leading whitespace and strip trailing whitespace."""
  return textwrap.dedent(value or "").strip()

@register.filter
def tojson(value) -> str:
  """Serialize Python objects to JSON for prompt rendering."""
  return json.dumps(value, ensure_ascii=False)