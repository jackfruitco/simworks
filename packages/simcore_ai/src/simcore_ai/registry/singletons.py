# simcore_ai/registry/singletons.py

from typing import overload, TypeVar, cast, Any

from simcore_ai.components.codecs.base import BaseCodec
from simcore_ai.components.promptkit.base import PromptSection
from simcore_ai.components.schemas import BaseOutputSchema
from simcore_ai.components.services.base import BaseService
from simcore_ai.identity.identity import Identity
from simcore_ai.registry.base import BaseRegistry

_coerce = Identity.get

services: BaseRegistry[Identity, BaseService] = BaseRegistry(coerce_key=_coerce)
codecs: BaseRegistry[Identity, BaseCodec] = BaseRegistry(coerce_key=_coerce)
schemas: BaseRegistry[Identity, BaseOutputSchema] = BaseRegistry(coerce_key=_coerce)
prompt_sections: BaseRegistry[Identity, PromptSection] = BaseRegistry(coerce_key=_coerce)

# Typed overloads for precise return types
TSvc = TypeVar("TSvc", bound=BaseService)
TCod = TypeVar("TCod", bound=BaseCodec)
TSch = TypeVar("TSch", bound=BaseOutputSchema)
TPS = TypeVar("TPS", bound=PromptSection)


@overload
def get_registry_for(component_type: type[TSvc]) -> BaseRegistry[Identity, TSvc]: ...


@overload
def get_registry_for(component_type: type[TCod]) -> BaseRegistry[Identity, TCod]: ...


@overload
def get_registry_for(component_type: type[TSch]) -> BaseRegistry[Identity, TSch]: ...


@overload
def get_registry_for(component_type: type[TPS]) -> BaseRegistry[Identity, TPS]: ...


# -----------------------------------------------------------------------------------------
# ---------- Implementation ---------------------------------------------------------------
# -----------------------------------------------------------------------------------------
def get_registry_for(component_type: type[Any]) -> BaseRegistry[Identity, Any] | None:
    """
    Return the global registry singleton corresponding to the given component type.

    Supports BaseService, BaseCodec, BaseOutputSchema, and PromptSection.
    Providers are not Identity-keyed and are resolved separately.
    """
    if issubclass(component_type, BaseService):
        return cast(BaseRegistry[Identity, Any], services)
    if issubclass(component_type, BaseCodec):
        return cast(BaseRegistry[Identity, Any], codecs)
    if issubclass(component_type, BaseOutputSchema):
        return cast(BaseRegistry[Identity, Any], schemas)
    if issubclass(component_type, PromptSection):
        return cast(BaseRegistry[Identity, Any], prompt_sections)
    return None
