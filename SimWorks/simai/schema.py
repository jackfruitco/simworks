import importlib

import graphene
from core.utils import Formatter
from django.core.exceptions import ObjectDoesNotExist
from graphene_django.types import DjangoObjectType
from simai.prompts import PromptModifiers
from simcore.schema import SimulationType

from .models import Response


class Modifier(graphene.ObjectType):
    key = graphene.String()
    name = graphene.String()
    group = graphene.String()
    description = graphene.String()


class ModifierGroup(graphene.ObjectType):
    group = graphene.String()
    description = graphene.String()
    modifiers = graphene.List(Modifier)


class ResponseType(DjangoObjectType):
    """Response type for GraphQL"""

    output_pretty = graphene.JSONString()

    class Meta:
        model = Response
        interfaces = (graphene.relay.Node,)
        fields = (
            "id",
            "created",
            "modified",
            "raw",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "user",
            "simulation",
        )

    def resolve_output_pretty(self, info):
        if not getattr(self, "raw", None):
            return None
        try:
            formatter = Formatter(self.raw)
            return formatter.render(format_type="json", indent=2)
        except Exception:
            return None


def get_modifier_groups():
    modifier_items = PromptModifiers.list()
    grouped = {}
    docstrings = {}

    for item in modifier_items:
        full_path = item["key"]
        group = item["group"]
        name = item["name"]
        description = item["description"]
        grouped.setdefault(group, []).append(
            {
                "key": full_path,
                "name": name,
                "group": group,
                "description": description,
            }
        )

    for group in grouped:
        try:
            module = importlib.import_module(f"simai.prompts.builtins._{group.lower()}")
            docstrings[group] = (module.__doc__ or "").strip()
        except Exception:
            docstrings[group] = ""

    for mods in grouped.values():
        mods.sort(key=lambda m: m["description"].lower())

    return [
        {"group": group, "description": docstrings[group], "modifiers": mods}
        for group, mods in sorted(grouped.items(), key=lambda item: item[0].lower())
    ]


class Query(graphene.ObjectType):

    # Responses
    response = graphene.Field(ResponseType, id=graphene.ID(required=True))
    responses = graphene.List(
        ResponseType,
        limit=graphene.Int(),
        simulation=graphene.ID(),
        ids=graphene.List(graphene.ID),
    )

    # Modifiers
    modifier = graphene.Field(Modifier, key=graphene.String(required=True))
    modifiers = graphene.List(Modifier)

    # Modifier Groups
    modifier_group = graphene.Field(ModifierGroup, group=graphene.String(required=True))
    modifier_groups = graphene.List(
        ModifierGroup, groups=graphene.List(graphene.String)
    )

    def resolve_response(root, info, id):
        try:
            return Response.objects.get(pk=id)
        except ObjectDoesNotExist:
            return None

    def resolve_responses(
        root, info, ids=None, limit: int = None, simulation: int = None
    ):
        qs = Response.objects.all()
        if ids:
            qs = qs.filter(pk__in=ids)
        if simulation:
            qs = qs.filter(simulation=simulation)
        if limit:
            qs = qs[:limit]
        return qs

    def resolve_modifier(root, info, key):
        item = PromptModifiers.get(key)
        if not item:
            return None
        func = item["value"]
        description = item["description"] or key
        try:
            value = func()
        except Exception:
            value = None
        return Modifier(
            key=item["key"],
            name=item["name"],
            group=item["group"],
            description=description,
        )

    def resolve_modifiers(root, info, group=None):
        modifier_items = PromptModifiers.list()
        result = []
        for item in modifier_items:
            func = item["value"]
            description = item["description"] or item["key"]
            try:
                value = func()
            except Exception:
                value = None
            if group and item["group"] != group:
                continue
            result.append(
                Modifier(
                    key=item["key"],
                    name=item["name"],
                    group=item["group"],
                    description=description,
                )
            )
        return result

    def resolve_modifier_group(root, info, group):
        grouped = get_modifier_groups()
        normalized = group.lower()
        for g in grouped:
            if g["group"].lower() == normalized:
                return g
        return None

    def resolve_modifier_groups(root, info, groups=None):
        grouped = get_modifier_groups()
        if groups:
            normalized_groups = [g.lower() for g in groups]
            grouped = [g for g in grouped if g["group"].lower() in normalized_groups]
        return grouped


class Mutation(graphene.ObjectType):
    pass
