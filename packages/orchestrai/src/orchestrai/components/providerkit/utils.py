# orchestrai/components/providerkit/utils.py
from typing import TYPE_CHECKING

from .exceptions import ProviderConfigurationError
from ...identity import Identity
from ...identity.exceptions import IdentityResolutionError
from ...registry import provider_backends
from ...registry.exceptions import RegistryLookupError

if TYPE_CHECKING:
    from .base import BaseProvider


def parse_backend_identity(value: str) -> Identity:
    """
    Parse a backend identity string like 'provider.openai.responses.backend'.

    This is the ONLY place where backend identities are parsed.
    `alias` strings no longer participate in identity logic.
    """
    try:
        return Identity.get(value)
    except IdentityResolutionError as exc:
        raise ProviderConfigurationError(
            f"Invalid backend identity {value!r}"
        ) from exc


def get_backend_class(backend_identity: str) -> type["BaseProvider"]:
    """
    Resolve and return the backend provider class.

    Parameters
    ----------
    backend_identity : str
        A full identity string such as 'provider.openai.responses.backend'.

    Raises
    ------
    ProviderConfigurationError
        If the backend cannot be resolved.
    """
    ident = parse_backend_identity(backend_identity)

    try:
        backend_cls: type["BaseProvider"] = provider_backends.get(ident)
    except RegistryLookupError as err:
        raise ProviderConfigurationError(
            f"Backend identity {backend_identity!r} not registered "
            f"(expected one of: {provider_backends.keys(as_csv=True)})"
        ) from err

    return backend_cls
