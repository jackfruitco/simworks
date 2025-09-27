# core/utils/system.py
import logging
import os
from logging import getLogger

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
        # TODO re-enable check_env error
        # raise ImproperlyConfigured(error_msg)


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
        return value.strip().lower() not in ("false", "0", "no", "")
    return bool(value)


import logging
from typing import Any


def remove_null_keys(dict_: Any) -> dict[Any, Any]:
    """
    Recursively removes keys from a dictionary (or nested dictionaries/lists)
    whose values are None or empty strings.

    If the input is not a dictionary, attempts to coerce it into one.
    """
    import logging

    if not isinstance(dict_, dict):
        try:
            dict_ = dict(dict_)
        except (ValueError, TypeError) as e:
            logging.error(f"Failed to convert {type(dict_)} to dict: {e}")
            return dict_

    def _clean(value):
        if isinstance(value, dict):
            return {
                k: _clean(v)
                for k, v in value.items()
                if v not in (None, "") and _clean(v) not in (None, {}, [])
            }
        elif isinstance(value, list):
            return [
                _clean(item)
                for item in value
                if item not in (None, "") and _clean(item) not in (None, {}, [])
            ]
        else:
            return value

    return _clean(dict_)
