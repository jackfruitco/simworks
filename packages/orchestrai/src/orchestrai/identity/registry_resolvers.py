# orchestrai/identity/registry_resolvers.py


import importlib
import inspect
from typing import TypeVar, Optional, TYPE_CHECKING

from orchestrai.components.exceptions import ComponentNotFoundError
from orchestrai.registry.exceptions import RegistryNotFoundError
from .identity import Identity, IdentityLike

from ..types.protocols import RegistryProtocol

if TYPE_CHECKING:
    from ..registry import BaseRegistry

T = TypeVar("T")


def coerce_identity(value: IdentityLike) -> Identity:
    return Identity.get_for(value)


def label(ident: IdentityLike) -> str:
    return Identity.get_for(ident).as_str


def tuple4(ident: IdentityLike) -> tuple[str, str, str, str]:
    return Identity.get_for(ident).as_tuple4


def from_(ident: IdentityLike) -> Identity:
    return Identity.get_for(ident)


def _resolve_component_type(component_type: type[T] | str) -> type[T]:
    """
    Normalize `component_type` into a concrete class.

    Accepts:
        - A class (BaseComponent subclass)
        - A string "path.to.module:ClassName" or "path.to.module.ClassName"
    """
    # Already a class
    if inspect.isclass(component_type):
        return component_type  # type: ignore[return-value]

    if not isinstance(component_type, str):
        raise TypeError(f"Invalid component_type: {component_type!r}")

    # Support "module:Class" and "module.Class"
    if ":" in component_type:
        module_path, class_name = component_type.split(":", 1)
    else:
        module_path, _, class_name = component_type.rpartition(".")

    if not module_path or not class_name:
        raise ComponentNotFoundError(
            f"Invalid component reference {component_type!r}; "
            "expected 'mod.path:ClassName' or 'mod.path.ClassName'"
        )

    module = importlib.import_module(module_path)
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        raise ComponentNotFoundError(
            f"No component class {class_name!r} in module {module_path!r}"
        ) from e

    if not inspect.isclass(cls):
        raise ComponentNotFoundError(
            f"Resolved {component_type!r} but it is not a class"
        )

    return cls  # type: ignore[return-value]


def for_(
        component_type: type[T] | str,
        ident: IdentityLike,
        *,
        __from: RegistryProtocol | None | BaseRegistry = None,
) -> T:
    """
    Resolve a registered component of the given type by identity.

    Resolution order:
      1) `__from` registry (if provided)
      2) component_type.get / component_type.try_get        # classmethods on component
      3) component_type.registry.get / .try_get             # attached registry on class
      4) get_registry_for(component_type).get / .try_get    # global registry dispatcher

    :param component_type: BaseComponent subclass object or name string
    :param ident: IdentityLike object
    :param __from: RegistryProtocol subclass object or name string

    :returns BaseComponent instance
    :raises RegistryNotFoundError: if no registry is found
    :raises ComponentNotFoundError: if no component is found
    """
    identity = Identity.get_for(ident)
    ident_key = identity.as_str

    # Normalize component type to a concrete class
    Component = _resolve_component_type(component_type)

    # Helper to prefer try_get() when present, otherwise fall back to get()
    def _resolve_via_registry(__registry: "BaseRegistry") -> T | None:
        try_get = getattr(__registry, "try_get", None)
        if callable(try_get):
            __found = try_get(identity) or try_get(ident_key)
            if __found is not None:
                return __found
        get_fn = getattr(__registry, "get", None)
        if callable(get_fn):
            try:
                return get_fn(identity)
            except (ComponentNotFoundError, RegistryNotFoundError, KeyError, AttributeError):
                pass
            try:
                return get_fn(ident_key)
            except (ComponentNotFoundError, RegistryNotFoundError, KeyError, AttributeError):
                pass
        return None

    # 1) Explicit registry (__from)
    if __from is not None:
        found = _resolve_via_registry(__from)
        if found is not None:
            return found
        # If an explicit registry was provided but did not contain the component,
        # fall through to the remaining resolution strategies instead of failing early.

    # 2) Component.get / Component.try_get
    get_fn = getattr(Component, "get", None)
    try_get_fn = getattr(Component, "try_get", None)

    if callable(try_get_fn):
        found = try_get_fn(identity) or try_get_fn(ident_key)
        if found is not None:
            return found

    if callable(get_fn):
        try:
            found = get_fn(identity)
        except (ComponentNotFoundError, RegistryNotFoundError, KeyError, AttributeError):
            found = None
        if found is not None:
            return found

        try:
            found = get_fn(ident_key)
        except (ComponentNotFoundError, RegistryNotFoundError, KeyError, AttributeError):
            found = None
        if found is not None:
            return found

    # 3) Attached registry on the component class
    __registry = getattr(Component, "registry", None)
    if __registry is not None:
        found = _resolve_via_registry(__registry)
        if found is not None:
            return found

    # 4) Global registry dispatcher
    from orchestrai.registry import get_registry_for

    try:
        global_registry = get_registry_for(Component)
    except RegistryNotFoundError:
        global_registry = None

    if global_registry is not None:
        found = _resolve_via_registry(global_registry)
        if found is not None:
            return found

    # Not found anywhere: hard failure for strict resolver
    raise ComponentNotFoundError(
        f"No component found for {ident!r} ({Component.__name__})"
    )


def try_for_(
        component_type: type[T] | str,
        ident: IdentityLike,
        *,
        __from: RegistryProtocol | None = None,
) -> Optional[T]:
    """
    Safe resolver variant.

    Returns:
        - The resolved component if found.
        - None if not found or if a registry/component lookup error occurs.
    """
    try:
        return for_(component_type, ident, __from=__from)
    except (ComponentNotFoundError, RegistryNotFoundError, NotImplementedError, TypeError):
        return None
