from django import template
from django.template.exceptions import TemplateDoesNotExist
from django.template.loader import get_template

register = template.Library()


@register.filter
def template_exists(template_name):
    """Returns True if the given template exists, False otherwise."""
    try:
        get_template(template_name)
        return True
    except TemplateDoesNotExist:
        return False


@register.simple_tag
def is_generic(tool):
    """
    Return True if tool.data is a list of dicts or objects with 'key' and 'value'.
    """
    data = getattr(tool, "data", None)
    if not isinstance(data, list):
        return False
    for item in data:
        if not hasattr(item, "key") or not hasattr(item, "value"):
            if not (isinstance(item, dict) and "key" in item and "value" in item):
                return False
    return True
