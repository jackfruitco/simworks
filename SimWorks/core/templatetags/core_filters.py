# core/templatetags/core_filters.py

import json
from django import template

register = template.Library()

@register.filter
def as_list(value):
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []

