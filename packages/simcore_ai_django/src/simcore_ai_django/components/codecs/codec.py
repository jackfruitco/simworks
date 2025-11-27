# simcore_ai_django/components/codecs/codecs.py
"""
This module provides the DjangoBaseCodec façade.

It subclasses the core BaseCodec and offers fan-out and persistence helpers
that are deprecated and will be moved to the service layer.
"""

import asyncio
import logging
import warnings
from typing import Any, ClassVar, Mapping, TypeVar, Callable
from asgiref.sync import async_to_sync

from core.models import PersistModel
from simcore_ai.components.codecs import BaseCodec
from simcore_ai.components.codecs.exceptions import CodecDecodeError
from simcore_ai.types import Response

logger = logging.getLogger(__name__)

__all__ = ("DjangoBaseCodec",)

M = TypeVar("M", bound=PersistModel)

class DjangoBaseCodec(BaseCodec):
    """
    DjangoBaseCodec is a Django-facing façade over the core BaseCodec.

    It provides asynchronous decoding and validation of payloads, along with
    deprecated fan-out and persistence behavior for Django model instances.

    The fan-out and persistence logic is **deprecated**. New code should prefer
    handling persistence in service `finalize()` methods. This logic will be
    removed in a later milestone.

    Two patterns are supported:

    1) Simple section→model:
         schema_model_map = {"input": Message, "metadata": SimulationMetadata}

    2) Routed by item "kind":
         schema_model_map = {"metadata": {"lab_result": LabResult, "rad_result": RadResult, "__default__": SimulationMetadata}}
         section_kind_field = {"metadata": "kind"}  # defaults to "kind" if not provided

    Optional key translations may be either flat per-section or routed per-kind:
         schema_key_translations = {
             "metadata": {"result_value": "value"},
             # or routed
             "metadata": {
                 "__default__": {"value": "value"},
                 "lab_result": {"result_value": "value", "flag": "result_flag"},
                 "rad_result": {"flag": "result_flag"},
             }
         }

    Section defaults allow pre-seeding fields (e.g., FKs) on each instance before apersist():
         section_defaults = {
             "input": {"role": "A", "is_from_ai": True},
             "metadata": lambda item: {"simulation": sim},  # callable per-item OK
         }
    """
    abstract: ClassVar[bool] = True

    # Map a section key in the validated payload to either:
    #   - a PersistModel subclass, or
    #   - a dict[str, PersistModelSubclass] that routes by item "kind".
    schema_model_map: dict[str, type[M] | dict[str, type[M]]] | None = None

    # Per-section key translation. Either flat dict[str,str] or routed dict[kind][src->dest].
    schema_key_translations: dict[str, dict[str, str] | dict[str, dict[str, str]]] | None = None

    # Which field on items holds the "kind" discriminator (per section)
    section_kind_field: dict[str, str] | None = None

    # Static defaults to set on new instances per section.
    # Values may be dicts or callables taking the item and returning a dict.
    section_defaults: dict[str, Mapping[str, Any] | Callable[[Mapping[str, Any]], Mapping[str, Any]]] | None = None

    # ---- public entrypoints ------------------------------------------------
    async def adecode(self, resp: Response) -> Any:
        """
        Decode a full Response, validate to the output schema (if any),
        and optionally persist sections via Django models.

        Returns:
            - None if there is no output schema / nothing to validate.
            - The validated payload if no persistence mapping is configured.
            - (validated, instances) tuple when persistence occurs.
        """
        # Let BaseCodec handle schema-aware validation / parsing first
        validated = await super().adecode(resp)
        if validated is None:
            return None

        vdict = self._normalize_validated_payload(validated)

        # If there is no mapping configured, just return the validated object
        if not self.schema_model_map:
            return validated

        # Fan-out persistence to configured models
        results = await self.persist_sections(vdict)
        logger.debug(
            "%s.persist_sections completed; sections=%s instances=%d",
            self.__class__.__name__,
            ", ".join((self.schema_model_map or {}).keys()),
            len(results),
        )
        return validated, results

    def decode(self, resp: Response) -> Any:
        """
        Sync wrapper for `adecode`. Prefer `adecode` in async call sites.
        """
        return async_to_sync(self.adecode)(resp)

    # Backwards-friendly aliases (arun/run) for callers that still use the old name.
    async def arun(self, resp: Response) -> Any:
        """Alias for `adecode` to support legacy call sites."""
        return await self.adecode(resp)

    def run(self, resp: Response) -> Any:
        """Alias for `decode` to support legacy call sites."""
        return self.decode(resp)

    # ---- internal helpers --------------------------------------------------
    def _normalize_validated_payload(self, validated: Any) -> Mapping[str, Any]:
        """
        Normalize a validated payload into a plain mapping suitable for section access.
        """
        if hasattr(validated, "model_dump"):
            # Pydantic v2 model
            return validated.model_dump(mode="python", exclude_none=True)  # type: ignore[return-value]
        if isinstance(validated, Mapping):
            return validated
        raise CodecDecodeError(f"{self.__class__.__name__}: unknown validated payload type {type(validated)!r}")

    # ---- core persistence --------------------------------------------------
    async def persist_sections(self, vdict: Mapping[str, Any]) -> list[PersistModel]:
        """
        DEPRECATED: Fan-out and persistence should be handled at the service layer.

        This method persists sections of the validated payload into Django model
        instances according to the schema_model_map and related configuration.

        Callers should prefer service-level persistence (e.g. in finalize() methods).
        """
        warnings.warn(
            "this method is deprecated; use service-level persistence instead",
            DeprecationWarning,
            stacklevel=2
        )

        coros: list[asyncio.Future] = []
        instances: list[PersistModel] = []

        for section_key, target in (self.schema_model_map or {}).items():
            items = vdict.get(section_key)
            if items is None:
                continue

            # normalize to sequence
            if isinstance(items, Mapping):
                seq = [items]
            elif isinstance(items, (list, tuple)):
                seq = list(items)
            else:
                raise CodecDecodeError(f"Section '{section_key}' must be object or list")

            # Router setup (if mapping by kind)
            kind_field = (self.section_kind_field or {}).get(section_key, "kind")
            routed = isinstance(target, dict)

            for item in seq:
                if not isinstance(item, Mapping):
                    raise CodecDecodeError(f"Items in section '{section_key}' must be mappings, not {type(item)!r}")

                # choose model class
                model_cls: type[M]
                if routed:
                    kind_val = str(item.get(kind_field, "__default__"))
                    model_cls = (target.get(kind_val) or target.get("__default__"))  # type: ignore[assignment]
                    if model_cls is None:
                        raise CodecDecodeError(
                            f"No model mapping for section '{section_key}' kind='{kind_val}' and no '__default__'"
                        )
                else:
                    model_cls = target  # type: ignore[assignment]

                # choose translations (flat or routed by kind)
                translate_map = None
                sec_trans = (self.schema_key_translations or {}).get(section_key)
                if isinstance(sec_trans, dict):
                    # either flat {"a":"b"} or routed {"__default__": {...}, "lab_result": {...}}
                    # detect routed shape by inner value types
                    if sec_trans and all(isinstance(v, dict) for v in sec_trans.values()):
                        kind_val = str(item.get(kind_field, "__default__"))
                        translate_map = sec_trans.get(kind_val) or sec_trans.get("__default__")  # type: ignore[assignment]
                    else:
                        translate_map = sec_trans  # type: ignore[assignment]

                # build instance with defaults (dict or callable)
                base_defaults = {}
                if self.section_defaults and section_key in self.section_defaults:
                    defaults_or_callable = self.section_defaults[section_key]
                    base_defaults = (
                        defaults_or_callable(item)  # type: ignore[arg-type]
                        if callable(defaults_or_callable)
                        else dict(defaults_or_callable)
                    )

                instance = model_cls(**base_defaults)  # type: ignore[call-arg]
                instances.append(instance)

                coros.append(
                    instance.apersist(item, translate_keys=translate_map)
                )

        if not coros:
            return []

        await asyncio.gather(*coros, return_exceptions=False)
        return instances
