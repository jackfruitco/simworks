# simcore_ai/registry/singletons.py
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload, cast

from simcore_ai.identity.identity import Identity
from simcore_ai.registry.base import BaseRegistry

if TYPE_CHECKING:
    # Only imported for typing; avoids runtime circular imports.
    from simcore_ai.components.codecs.codec import BaseCodec
    from simcore_ai.components.promptkit.base import PromptSection
    from simcore_ai.components.schemas import BaseOutputSchema
    from simcore_ai.components.services.service import BaseService

    TSvc = TypeVar("TSvc", bound="BaseService")
    TCod = TypeVar("TCod", bound="BaseCodec")
    TSch = TypeVar("TSch", bound="BaseOutputSchema")
    TPS = TypeVar("TPS", bound="PromptSection")

    ComponentKind = Literal["service", "codec", "schema", "prompt_section"]
    ComponentKey = (
        type["BaseService"]
        | type["BaseCodec"]
        | type["BaseOutputSchema"]
        | type["PromptSection"]
        | ComponentKind
    )

    @overload
    def get_registry_for(component: type[TSvc]) -> BaseRegistry[Identity, TSvc]: ...
    @overload
    def get_registry_for(component: type[TCod]) -> BaseRegistry[Identity, TCod]: ...
    @overload
    def get_registry_for(component: type[TSch]) -> BaseRegistry[Identity, TSch]: ...
    @overload
    def get_registry_for(component: type[TPS]) -> BaseRegistry[Identity, TPS]: ...
    @overload
    def get_registry_for(kind: ComponentKind) -> BaseRegistry[Identity, Any]: ...
else:
    # At runtime we don’t need precise typing – keep it loose.
    ComponentKind = str  # type: ignore[assignment]
    ComponentKey = Any  # type: ignore[assignment]

_coerce = Identity.get

# Global registries keyed by Identity.
services: BaseRegistry[Identity, Any] = BaseRegistry(coerce_key=_coerce)
codecs: BaseRegistry[Identity, Any] = BaseRegistry(coerce_key=_coerce)
schemas: BaseRegistry[Identity, Any] = BaseRegistry(coerce_key=_coerce)
prompt_sections: BaseRegistry[Identity, Any] = BaseRegistry(coerce_key=_coerce)


def _infer_kind_from_type(component_type: type[Any]) -> str | None:
    """
    Infer the registry kind for a component type using lazy imports.

    This keeps the strong type-based ergonomics (cls → registry) while avoiding
    hard import cycles at module import time.
    """
    try:
        from simcore_ai.components.services.service import (  # type: ignore[import-not-found]
            BaseService as _BaseService,
        )
        from simcore_ai.components.codecs.codec import (  # type: ignore[import-not-found]
            BaseCodec as _BaseCodec,
        )
        from simcore_ai.components.schemas import (  # type: ignore[import-not-found]
            BaseOutputSchema as _BaseOutputSchema,
        )
        from simcore_ai.components.promptkit.base import (  # type: ignore[import-not-found]
            PromptSection as _PromptSection,
        )
    except Exception:
        # If anything goes sideways during lazy import, bail out and let the
        # caller decide how to handle a missing registry.
        return None

    if issubclass(component_type, _BaseService):
        return "service"
    if issubclass(component_type, _BaseCodec):
        return "codec"
    if issubclass(component_type, _BaseOutputSchema):
        return "schema"
    if issubclass(component_type, _PromptSection):
        return "prompt_section"
    return None


def get_registry_for(component: ComponentKey) -> BaseRegistry[Identity, Any] | None:
    """
    Return the global registry singleton corresponding to the given component.

    Supports two calling styles:

        • Type-based:
            get_registry_for(MyServiceSubclass)  -> service registry
            get_registry_for(MyCodecSubclass)    -> codec registry

        • String-based:
            get_registry_for("service")
            get_registry_for("codec")
            get_registry_for("schema")
            get_registry_for("prompt_section")

    Providers are not Identity-keyed and are resolved separately.
    """
    # String-based (kind) dispatch
    if isinstance(component, str):
        kind = component
    else:
        # Type-based dispatch with lazy import of base component types
        kind = _infer_kind_from_type(component)
        if kind is None:
            return None

    if kind == "service":
        return cast(BaseRegistry[Identity, Any], services)
    if kind == "codec":
        return cast(BaseRegistry[Identity, Any], codecs)
    if kind == "schema":
        return cast(BaseRegistry[Identity, Any], schemas)
    if kind == "prompt_section":
        return cast(BaseRegistry[Identity, Any], prompt_sections)

    return None
