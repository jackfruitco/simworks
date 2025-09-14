import importlib

import strawberry
from strawberry import auto
from strawberry.django import type
from strawberry.scalars import JSON
from strawberry.types import Info
from django.core.exceptions import ObjectDoesNotExist

from core.utils import Formatter
from simai.prompts import PromptModifiers
from simcore.schema import SimulationType
from .models import Response


@strawberry.type
class Modifier:
    key: str
    name: str
    group: str
    description: str


@strawberry.type
class ModifierGroup:
    group: str
    description: str
    modifiers: list[Modifier]


@type(Response)
class ResponseType:
    id: auto
    created: auto
    modified: auto
    raw: auto
    input_tokens: auto
    output_tokens: auto
    reasoning_tokens: auto
    user: auto
    simulation: SimulationType
    output_pretty: JSON | None = None

    @strawberry.field
    def output_pretty(self) -> JSON | None:  # type: ignore[override]
        if not getattr(self, "raw", None):
            return None
        try:
            formatter = Formatter(self.raw)
            return formatter.render(format_type="json", indent=2)
        except Exception:
            return None


def get_modifier_groups() -> list[ModifierGroup]:
    """Return all modifier groups with their modifiers."""
    modifier_items = PromptModifiers.list()
    grouped: dict[str, list[Modifier]] = {}
    docstrings: dict[str, str] = {}

    for item in modifier_items:
        group = item["group"]
        modifier = Modifier(
            key=item["key"],
            name=item["name"],
            group=group,
            description=item["description"],
        )
        grouped.setdefault(group, []).append(modifier)

    for group in grouped:
        try:
            module = importlib.import_module(f"simai.prompts.builtins._{group.lower()}")
            docstrings[group] = (module.__doc__ or "").strip()
        except Exception:
            docstrings[group] = ""

    for mods in grouped.values():
        mods.sort(key=lambda m: m.description.lower())

    return [
        ModifierGroup(group=group, description=docstrings[group], modifiers=mods)
        for group, mods in sorted(grouped.items(), key=lambda item: item[0].lower())
    ]


@strawberry.type
class Query:
    @strawberry.field
    def response(self, info: Info, id: strawberry.ID) -> ResponseType | None:
        try:
            return Response.objects.get(pk=id)
        except ObjectDoesNotExist:
            return None

    @strawberry.field
    def responses(
        self,
        info: Info,
        ids: list[strawberry.ID] | None = None,
        limit: int | None = None,
        simulation: strawberry.ID | None = None,
    ) -> list[ResponseType]:
        qs = Response.objects.all()
        if ids:
            qs = qs.filter(pk__in=ids)
        if simulation:
            qs = qs.filter(simulation=simulation)
        if limit:
            qs = qs[:limit]
        return list(qs)

    @strawberry.field
    def modifier(self, info: Info, key: str) -> Modifier | None:
      codex/migrate-to-strawberry-graphql-django
        item = PromptModifiers.get(key)
        if not item:
            return None
        return Modifier(
            key=item["key"],
            name=item["name"],
            group=item["group"],
            description=item["description"] or key,
        )

    @strawberry.field
    def modifiers(self, info: Info, group: str | None = None) -> list[Modifier]:
      codex/migrate-to-strawberry-graphql-django
        modifier_items = PromptModifiers.list()
        result: list[Modifier] = []
        for item in modifier_items:
            if group and item["group"] != group:
                continue
            result.append(
                Modifier(
                    key=item["key"],
                    name=item["name"],
                    group=item["group"],
                    description=item["description"] or item["key"],
                )
            )
        return result

    @strawberry.field
    def modifier_group(self, info: Info, group: str) -> dict | None:
      codex/migrate-to-strawberry-graphql-django
        grouped = get_modifier_groups()
        normalized = group.lower()
        for g in grouped:
            if g.group.lower() == normalized:
                return g
        return None

    @strawberry.field
    def modifier_groups(
        self, info: Info, groups: list[str] | None = None
    ) -> list[dict]:
      codex/migrate-to-strawberry-graphql-django
        grouped = get_modifier_groups()
        if groups:
            normalized_groups = [g.lower() for g in groups]
            grouped = [g for g in grouped if g.group.lower() in normalized_groups]
        return grouped


@strawberry.type
class Mutation:
    pass

