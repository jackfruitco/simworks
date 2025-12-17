"""Mapping-like configuration inspired by Celery settings handling."""


import importlib
import os
from collections import ChainMap
from typing import Any, Iterable, Iterator, Mapping, MutableMapping

from .defaults import DEFAULTS


class Settings(MutableMapping[str, Any]):
    """Layered settings with defaults and optional overlays."""

    def __init__(self, *layers: Mapping[str, Any]) -> None:
        self._storage = ChainMap({}, *(dict(layer) for layer in layers), dict(DEFAULTS))

    # Mapping protocol -------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._storage[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._storage.maps[0][key] = value

    def __delitem__(self, key: str) -> None:
        del self._storage.maps[0][key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._storage)

    def __len__(self) -> int:
        return len(self._storage)

    # Helpers ----------------------------------------------------------
    def update_from_object(self, obj: str, *, namespace: str | None = None) -> None:
        module = importlib.import_module(obj)
        self.update_from_mapping(_filter_by_namespace(vars(module), namespace))

    def update_from_envvar(self, envvar: str = "ORCHESTRAI_CONFIG_MODULE", *, namespace: str | None = None) -> None:
        module_name = os.environ.get(envvar)
        if not module_name:
            return
        self.update_from_object(module_name, namespace=namespace)

    def update_from_mapping(self, mapping: Mapping[str, Any], *, namespace: str | None = None) -> None:
        self._storage.maps[0].update(_filter_by_namespace(mapping, namespace))

    def as_dict(self) -> dict[str, Any]:
        return dict(self._storage)


def _filter_by_namespace(mapping: Mapping[str, Any], namespace: str | None) -> dict[str, Any]:
    if namespace is None:
        return {k: v for k, v in mapping.items() if k.isupper()}

    prefix = f"{namespace}_"
    output: dict[str, Any] = {}
    for key, value in mapping.items():
        if not key.startswith(prefix):
            continue
        short_key = key[len(prefix) :]
        output[short_key] = value
    return output

