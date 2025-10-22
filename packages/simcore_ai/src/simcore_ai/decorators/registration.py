from __future__ import annotations

import logging
import os
import re
from typing import Any, ClassVar, Iterable, Optional, Type, Union

from simcore_ai.identity.utils import snake

_logger = logging.getLogger(__name__)


def _derive_from_module(module_name: str) -> dict[str, str]:
    """
    Derives default identity attributes from the module name.

    Args:
        module_name: The module name string.

    Returns:
        A dictionary with default identity attributes:
        - "name": snake-cased last module component
        - "version": "v1"
        - "namespace": snake-cased first module component
    """
    parts = module_name.split(".")
    if not parts:
        return {"name": "unknown", "version": "v1", "namespace": "unknown"}

    name = snake(parts[-1])
    namespace = snake(parts[0])
    version = "v1"
    return {"name": name, "version": version, "namespace": namespace}


def _strip_affixes_casefold(
        value: str, affixes: Iterable[str]
) -> str:
    """
    Strips affixes from both ends of the string iteratively, case-insensitive.

    Args:
        value: The string to strip affixes from.
        affixes: Iterable of affix strings to remove from both ends.

    Returns:
        The stripped string.
    """
    if not value or not affixes:
        return value

    affixes_cf = {a.casefold() for a in affixes}
    val_cf = value.casefold()

    changed = True
    while changed and value:
        changed = False
        for affix in affixes_cf:
            affix_len = len(affix)
            if val_cf.startswith(affix):
                value = value[affix_len:]
                val_cf = value.casefold()
                changed = True
            if val_cf.endswith(affix):
                value = value[:-affix_len]
                val_cf = value.casefold()
                changed = True
    return value


def _parse_env_tokens() -> set[str]:
    """
    Parses the environment variable SIMCORE_AI_IDENTITY_STRIP_TOKENS to get strip tokens.

    Returns:
        A set of tokens from the environment variable, split by comma or whitespace.
    """
    env_value = os.environ.get("SIMCORE_AI_IDENTITY_STRIP_TOKENS", "")
    if not env_value:
        return set()
    # Split by commas or whitespace
    tokens = re.split(r"[\s,]+", env_value.strip())
    return {t for t in tokens if t}


class BaseRegistrationDecorator:
    """
    Base class for registration decorators.

    This class provides helper methods to resolve the identity of the decorated
    class or function, strip affixes from the name, and supports dual-form usage
    of the decorator.

    Subclasses should override:
        - register()
        - bind_extras()
        - wrap_function()

    The decorator instance is stateless and logs warnings or debug information
    but never raises exceptions during registration.
    """

    _strip_tokens_env: ClassVar[set[str]] = _parse_env_tokens()

    def __init__(self, **kwargs: Any):
        """
        Initializes the decorator with optional identity attributes.

        Args:
            kwargs: Optional identity attributes such as name, version, namespace.
        """
        self._kwargs = kwargs

    def strip_tokens(self) -> set[str]:
        """
        Returns the set of tokens to strip from the name.

        Returns:
            A set of tokens including environment tokens.
        """
        # Default empty set, subclasses or instances may override or extend
        return set() | self._strip_tokens_env

    def collect_strip_tokens(self, extra_tokens: Optional[Iterable[str]] = None) -> set[str]:
        """
        Collects strip tokens combining decorator tokens and extra tokens.

        Args:
            extra_tokens: Optional extra tokens to include.

        Returns:
            A combined set of tokens to strip.
        """
        tokens = set(self.strip_tokens())
        if extra_tokens:
            # Be defensive: only add string-like tokens
            for t in extra_tokens:
                if isinstance(t, str):
                    tokens.add(t)
        return tokens

    def _strip_affixes_casefold(self, value: str, affixes: Iterable[str]) -> str:
        """
        Instance-level shim so mixins/decorators can call a consistent API.

        Delegates to the module-level `_strip_affixes_casefold` implementation.
        """
        return _strip_affixes_casefold(value, affixes)

    @staticmethod
    def _bump_suffix(name: str) -> str:
        """Return `name-2` or increment an existing trailing `-N` suffix."""
        if "-" not in name:
            return f"{name}-2"
        base, sep, tail = name.rpartition("-")
        if sep and tail.isdigit() and base:
            return f"{base}-{int(tail) + 1}"
        return f"{name}-2"

    def resolve_identity(
            self,
            cls: Optional[Type[Any]] = None,
            *,
            name: Optional[str] = None,
            version: Optional[str] = None,
            namespace: Optional[str] = None,
            strip_tokens: Optional[Iterable[str]] = None,
            **_ignored: Any
    ) -> dict[str, str]:
        """
        Resolves the identity attributes for the decorated class or function.

        Precedence: kwargs > class attributes > module-derived defaults.

        Args:
            cls: The decorated class or object.
            name: Optional explicit name.
            version: Optional explicit version.
            namespace: Optional explicit namespace.
            strip_tokens: Optional extra tokens to strip from the name.

        Returns:
            A dictionary with keys "name", "version", "namespace".
        """
        # Start from module defaults
        identity = {}
        if cls is not None:
            module_name = getattr(cls, "__module__", None)
            if module_name:
                identity.update(_derive_from_module(module_name))
            else:
                identity.update({"name": "unknown", "version": "v1", "namespace": "unknown"})
        else:
            identity.update({"name": "unknown", "version": "v1", "namespace": "unknown"})

        # Override from class attributes if present
        if cls is not None:
            for attr in ("name", "version", "namespace"):
                val = getattr(cls, attr, None)
                if isinstance(val, str) and val:
                    identity[attr] = val

        # Override from decorator kwargs
        for attr in ("name", "version", "namespace"):
            val = self._kwargs.get(attr)
            if isinstance(val, str) and val:
                identity[attr] = val

        # Override from explicit call arguments
        if isinstance(name, str) and name:
            identity["name"] = name
        if isinstance(version, str) and version:
            identity["version"] = version
        if isinstance(namespace, str) and namespace:
            identity["namespace"] = namespace

        # Strip affixes only from the name, case-insensitive
        tokens = self.collect_strip_tokens(strip_tokens)
        if identity.get("name"):
            identity["name"] = self._strip_affixes_casefold(identity["name"], tokens)

        return identity

    def bind_extras(self, cls: Type[Any], *args: Any, **kwargs: Any) -> None:
        """
        Hook to bind extra information or perform additional registration steps.

        Subclasses should override this method.

        Args:
            cls: The class being decorated.
            args: Additional positional arguments.
            kwargs: Additional keyword arguments.
        """
        pass  # no-op base implementation

    def log_custom(self, cls: Optional[Type[Any]] = None, *args: Any, **kwargs: Any) -> None:
        """Simple method used in __call__ provided to subclasses."""
        pass

    def register(self, cls: Type[Any], identity: tuple[str, str, str], **kwargs) -> None:
        """
        Performs the registration of the class or function.

        Subclasses should override this method.

        Args:
            cls: The class or function being registered.
            identity: The resolved identity dictionary.
        """
        pass  # no-op base implementation

    def wrap_function(self, func: Any) -> Any:
        """
        Wraps the decorated function.

        The base implementation raises TypeError because only Services should override it.

        Args:
            func: The function to wrap.

        Returns:
            The wrapped function.

        Raises:
            TypeError: Always in base class.
        """
        raise TypeError(
            f"{self.__class__.__name__} does not support function wrapping; "
            "only Services should override wrap_function."
        )

    def __call__(self, arg: Optional[Union[Type[Any], Any]] = None, **kwargs: Any) -> Any:
        """
        Supports dual-form decorator usage: @decorator and @decorator(...).

        Args:
            arg: The class or function being decorated, or None if called with parameters.
            kwargs: Optional keyword arguments for the decorator.

        Returns:
            The decorated class/function or a decorator partial.
        """
        self.log_custom(arg, **kwargs)

        if arg is not None and callable(arg) and not kwargs:
            # Used as @decorator without parameters
            return self._decorate(arg)
        else:
            # Used as @decorator(...) with parameters
            # Create a new decorator instance with updated kwargs
            new_kwargs = dict(self._kwargs)
            new_kwargs.update(kwargs)
            decorator_instance = self.__class__(**new_kwargs)
            if arg is not None:
                # arg is the decorated object
                return decorator_instance._decorate(arg)
            return decorator_instance

    def _decorate(self, cls_or_func: Union[Type[Any], Any]) -> Union[Type[Any], Any]:
        """
        Internal method to perform decoration.

        Args:
            cls_or_func: The class or function to decorate.

        Returns:
            The decorated class or function.
        """
        try:
            explicit_origin = getattr(cls_or_func, "origin", None)
            explicit_bucket = getattr(cls_or_func, "bucket", None)
            explicit_name = getattr(cls_or_func, "name", None)

            identity = self.resolve_identity(
                cls_or_func,
                origin=explicit_origin,
                bucket=explicit_bucket,
                name=explicit_name,
            )
            self.register(cls_or_func, identity)
            self.bind_extras(cls_or_func)
            if callable(cls_or_func) and not isinstance(cls_or_func, type):
                # It's a function or callable object, wrap it
                wrapped = self.wrap_function(cls_or_func)
                return wrapped
            return cls_or_func
        except Exception as ex:
            _logger.warning(
                "Registration failed for %r with error: %s", cls_or_func, ex, exc_info=True
            )
            # Return original object on failure to avoid breaking decoration
            return cls_or_func
