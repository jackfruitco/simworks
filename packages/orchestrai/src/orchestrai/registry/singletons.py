from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload, cast, TypeAlias

from orchestrai.identity.identity import Identity
from orchestrai.registry.base import ComponentRegistry

if TYPE_CHECKING:
    # Only imported for typing; avoids runtime circular imports.
    from orchestrai.components.codecs.codec import BaseCodec
    from orchestrai.components.promptkit.base import PromptSection
    from orchestrai.components.schemas import BaseOutputSchema
    from orchestrai.components.services.service import BaseService
    from orchestrai.components.providerkit import BaseProvider

    TSvc = TypeVar("TSvc", bound="BaseService")
    TCod = TypeVar("TCod", bound="BaseCodec")
    TSch = TypeVar("TSch", bound="BaseOutputSchema")
    TPS = TypeVar("TPS", bound="PromptSection")
    TPrv = TypeVar("TPrv", bound="BaseProvider")

    ComponentKey: TypeAlias = (
            type[BaseService]
            | type[BaseCodec]
            | type[BaseOutputSchema]
            | type[PromptSection]
            | type[BaseProvider]
    )

    ComponentKeyAliases: TypeAlias = Literal[
        "service",
        "codec",
        "schema",
        "prompt_section",
        "backend",
    ]

    ComponentKind: TypeAlias = ComponentKeyAliases

    ComponentKeyLike: TypeAlias = ComponentKey | ComponentKeyAliases


    @overload
    def get_registry_for(component: type[TSvc]) -> ComponentRegistry[TSvc]:
        ...


    @overload
    def get_registry_for(component: type[TCod]) -> ComponentRegistry[TCod]:
        ...


    @overload
    def get_registry_for(component: type[TSch]) -> ComponentRegistry[TSch]:
        ...


    @overload
    def get_registry_for(component: type[TPS]) -> ComponentRegistry[TPS]:
        ...


    @overload
    def get_registry_for(component: type[TPrv]) -> ComponentRegistry[TPrv]:
        ...


    @overload
    def get_registry_for(kind: ComponentKind) -> ComponentRegistry[Any]:
        ...
else:
    # At runtime we don’t need precise typing – keep it loose.
    ComponentKind = str  # type: ignore[assignment]
    ComponentKey = Any  # type: ignore[assignment]

# Global registries keyed by Identity.
services: ComponentRegistry[Any] = ComponentRegistry()
codecs: ComponentRegistry[Any] = ComponentRegistry()
schemas: ComponentRegistry[Any] = ComponentRegistry()
prompt_sections: ComponentRegistry[Any] = ComponentRegistry()

provider_backends: ComponentRegistry[Any] = ComponentRegistry()
providers: ComponentRegistry[Any] = ComponentRegistry()


def _infer_kind_from_type(component_type: type[Any]) -> str | None:
    """
    Infer the registry kind for a component type using lazy imports.

    This keeps the strong type-based ergonomics (cls → registry) while avoiding
    hard import cycles at module import time.
    """
    try:
        from orchestrai.components.services.service import (  # type: ignore[import-not-found]
            BaseService as _BaseService,
        )
        from orchestrai.components.codecs.codec import (  # type: ignore[import-not-found]
            BaseCodec as _BaseCodec,
        )
        from orchestrai.components.schemas import (  # type: ignore[import-not-found]
            BaseOutputSchema as _BaseOutputSchema,
        )
        from orchestrai.components.promptkit.base import (  # type: ignore[import-not-found]
            PromptSection as _PromptSection,
        )
        from orchestrai.components.providerkit import (  # type: ignore[import-not-found]
            BaseProvider as _BaseProvider
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
    if issubclass(component_type, _BaseProvider):
        return "backend"
    return None


def get_registry_for(component: ComponentKeyLike) -> ComponentRegistry[Any] | None:
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

    Providers have two registries:
      - Backends (Identity-keyed): returned here for kind == "backend".
      - Provider configs (Identity-keyed): available as `providers` and used for config discovery.
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
        return cast(ComponentRegistry[Any], services)
    if kind == "codec":
        return cast(ComponentRegistry[Any], codecs)
    if kind == "schema":
        return cast(ComponentRegistry[Any], schemas)
    if kind == "prompt_section":
        return cast(ComponentRegistry[Any], prompt_sections)
    if kind == "backend":
        return cast(ComponentRegistry[Any], provider_backends)

    return None
