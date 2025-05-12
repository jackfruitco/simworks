# core/utils/system.py
import os

from django.core.exceptions import ImproperlyConfigured

_SENTINEL = object()


def check_env(var_name, default=_SENTINEL):
    """
    Retrieves the environment variable or returns the default if provided.
    Raises ImproperlyConfigured if the variable is not found and no default is provided.

    :param var_name: The name of the environment variable.
    :param default: The default value to return if the variable is not found.
                    If not provided, an error is raised.
    :return: The environment variable value or the default.
    """
    try:
        return os.environ[var_name]
    except KeyError:
        if default is not _SENTINEL:
            return default
        error_msg = (
            f"{var_name} not found! Did you set the environment variable {var_name}?"
        )
        raise ImproperlyConfigured(error_msg)

def coerce_to_bool(value: str | bool | int) -> bool:
    """
    Converts a value to a boolean. Interprets common string representations
    of falsy values ('false', '0', 'no', etc.) as False.

    :param value: Input to coerce (str, bool, or int)
    :return: Boolean value
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ('false', '0', 'no', '')
    return bool(value)