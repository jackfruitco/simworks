from django.db import models


class ApiAccessControl(models.Model):
    """Dummy Model to create API permissions"""

    class Meta:
        permissions = [
            ("read_api", "Can read API"),
            ("write_api", "Can write API"),
        ]

# simcore_ai_django/models/mixins.py
from __future__ import annotations
from typing import Any, Iterable, Mapping, Sequence, Self

from asgiref.sync import iscoroutinefunction
from channels.db import database_sync_to_async
from django.core.exceptions import FieldDoesNotExist, ValidationError as DjangoValidationError
from django.db import models, transaction
from django.utils import timezone


class PersistModel(models.Model):
    """
    Async-first persistence helpers for all SimWorks models.
    """

    class Meta:
        abstract = True

    # -------- field utilities --------
    @classmethod
    def _field_names(cls) -> set[str]:
        return {f.name for f in cls._meta.get_fields() if getattr(f, "concrete", True)}

    @classmethod
    def _translate_payload(
        cls,
        data: Mapping[str, Any],
        translate_keys: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if not translate_keys:
            return dict(data)
        out: dict[str, Any] = {}
        for k, v in data.items():
            dest = translate_keys.get(k, k)
            out[dest] = v
        return out

    # -------- async persistence API --------
    async def apersist(
        self: Self,
        data: Mapping[str, Any] | None = None,
        *,
        translate_keys: Mapping[str, str] | None = None,
        update_fields: Iterable[str] | None = None,
        using: str | None = None,
        clean: bool = True,
        make_aware: bool = True,
    ) -> Self:
        """
        Update self from 'data' and save. Safe to call from async code.
        """
        payload = self._translate_payload(data or {}, translate_keys)
        valid_fields = self._field_names()

        # normalize datetimes (optional)
        if make_aware:
            for k, v in list(payload.items()):
                if hasattr(v, "tzinfo") and getattr(v, "tzinfo", None) is None:
                    try:
                        payload[k] = timezone.make_aware(v, timezone.get_current_timezone())
                    except Exception:
                        pass

        # set attributes (ignore unknowns, but log them)
        unknown: list[str] = []
        for k, v in payload.items():
            if k in valid_fields:
                setattr(self, k, v)
            else:
                unknown.append(k)

        if unknown:
            # keep this mild; unknown keys are common when schemas evolve
            from logging import getLogger
            getLogger(__name__).debug(
                "Ignoring unknown fields for %s: %s", self.__class__.__name__, ", ".join(unknown)
            )

        @database_sync_to_async
        def _save_sync() -> None:
            if clean and hasattr(self, "full_clean"):
                self.full_clean()
            if update_fields:
                self.save(using=using, update_fields=list(update_fields))
            else:
                self.save(using=using)

        await _save_sync()
        return self

    # -------- convenience classmethods --------
    @classmethod
    async def acreate_from(
        cls,
        data: Mapping[str, Any],
        *,
        translate_keys: Mapping[str, str] | None = None,
        using: str | None = None,
        clean: bool = True,
    ) -> Self:
        obj = cls()  # type: ignore[call-arg]
        return await obj.aperist(data, translate_keys=translate_keys, using=using, clean=clean)

    # small typo guard: keep both spellings just in case muscle memory kicks in :)
    async def aperist(self, *a, **kw):  # pragma: no cover
        return await self.apersist(*a, **kw)

    @classmethod
    async def aupdate_or_create_from(
        cls,
        *,
        lookup: Mapping[str, Any],
        data: Mapping[str, Any],
        translate_keys: Mapping[str, str] | None = None,
        using: str | None = None,
        clean: bool = True,
    ) -> Self:
        """
        Async upsert: find by 'lookup', apply 'data', save.
        """
        from django.db.models import Q

        @database_sync_to_async
        def _get_or_create():
            q = Q()
            for k, v in lookup.items():
                q &= Q(**{k: v})
            obj = cls._default_manager.using(using).filter(q).first()
            created = False
            if obj is None:
                obj = cls()  # type: ignore
                created = True
            return obj, created

        obj, _ = await _get_or_create()
        return await obj.apersist(data, translate_keys=translate_keys, using=using, clean=clean)