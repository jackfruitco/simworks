import importlib

import strawberry
import strawberry_django
from strawberry import auto, LazyType
from strawberry.scalars import JSON

from core.utils import Formatter
from simai.prompts import PromptModifiers
from .models import Response

SimulationType = LazyType("SimulationType", "simcore.schema")

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


@strawberry_django.type(Response)
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
class SimAiQuery:
    @strawberry_django.field
    def response(self, info: strawberry.Info, _id: strawberry.ID) -> ResponseType:
        return Response.objects.select_related("simulation").get(id=_id)

    @strawberry_django.field
    def responses(
        self,
        info: strawberry.Info,
        _ids: list[strawberry.ID] | None = None,
        limit: int | None = None,
        simulation: strawberry.ID | None = None,
    ) -> list[ResponseType]:
        qs = Response.objects.select_related("simulation").all()
        if _ids:
            qs = qs.filter(pk__in=_ids)
        if simulation:
            qs = qs.filter(simulation=simulation)
        if limit:
            qs = qs[:limit]
        return qs

    @strawberry.field
    def modifier(self, info: strawberry.Info, key: str) -> Modifier | None:
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
    def modifiers(self, info: strawberry.Info, group: str | None = None) -> list[Modifier]:
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
    def modifier_group(self, info: strawberry.Info, group: str) -> ModifierGroup | None:
        grouped = get_modifier_groups()
        normalized = group.lower()
        for g in grouped:
            if g.group.lower() == normalized:
                return g
        return None

    @strawberry.field
    def modifier_groups(
        self, info: strawberry.Info, groups: list[str] | None = None
    ) -> list[ModifierGroup]:
        grouped = get_modifier_groups()
        if groups:
            normalized_groups = [g.lower() for g in groups]
            grouped = [g for g in grouped if g.group.lower() in normalized_groups]
        return grouped


@strawberry.type
class SimAiMutation:
    pass

