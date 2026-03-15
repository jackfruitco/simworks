# common/templatetags/core_filters.py
import json

from django import template
from django.core.serializers.json import DjangoJSONEncoder

register = template.Library()


@register.filter
def as_list(value):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []


@register.filter
def json_pretty(value):
    """Pretty-print a dict/list as indented JSON for display in <pre> tags."""
    try:
        return json.dumps(value, cls=DjangoJSONEncoder, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
