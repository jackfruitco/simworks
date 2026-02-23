"""
This module provides a function to convert strings to PascalCase format.

The module includes a utility function to transform strings that use
underscore-based delimiters or other formats into PascalCase.
"""

import re


def to_pascal_case(s: str) -> str:
    """
    Convert a string to PascalCase.

    Args:
        s (str): The string to convert.

    Returns:
        The converted string in PascalCase

    Examples:
        - `foo_bar` -> `FooBar`
        - `FOO_BAR` -> `FooBar`
        - `fooBar` -> `FooBar`
        - `foo` -> `Foo`
    """
    return "".join(part.capitalize() for part in s.split("_"))


def to_snake_case(s: str) -> str:
    """
    Convert a CamelCase, PascalCase, or delimited string to snake_case.

    Args:
        s: The string to convert.

    Returns:
        The converted string in snake_case.

    Examples:
        - `FooBar` -> `foo_bar`
        - `fooBar` -> `foo_bar`
        - `foo-bar` -> `foo_bar`
        - `foo bar` -> `foo_bar`
    """
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
    s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
    return re.sub(r'[_\-\s]+', '_', s2).lower()


def to_camel_case(s: str) -> str:
    """
    Convert a snake_case, PascalCase, or delimited string to camelCase.

    Args:
        s: The string to convert.

    Returns:
        The converted string in camelCase.

    Examples:
        - `foo_bar` -> `fooBar`
        - `FooBar` -> `fooBar`
        - `foo-bar` -> `fooBar`
        - `foo bar` -> `fooBar`
    """
    parts = re.split(r'[_\-\s]+', s)
    first, rest = parts[0].lower(), [p.capitalize() for p in parts[1:]]
    return ''.join([first] + rest)
