from django import template
from django.http import QueryDict
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
        if (not hasattr(item, "key") or not hasattr(item, "value")) and not (
            isinstance(item, dict) and "key" in item and "value" in item
        ):
            return False
    return True


@register.simple_tag
def url_with_query(base_url, query_params=None, **updates):
    if isinstance(query_params, QueryDict):
        merged = query_params.copy()
    else:
        merged = QueryDict("", mutable=True)

    for key, value in updates.items():
        if value in (None, ""):
            merged.pop(key, None)
            continue

        if isinstance(value, (list, tuple)):
            merged.setlist(key, [str(item) for item in value])
            continue

        merged[key] = value

    encoded = merged.urlencode()
    if not encoded:
        return base_url
    return f"{base_url}?{encoded}"
