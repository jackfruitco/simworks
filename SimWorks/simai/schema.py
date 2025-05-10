import graphene
from simai.prompts import PromptModifiers
import importlib


class Modifier(graphene.ObjectType):
    key = graphene.String()
    name = graphene.String()
    group = graphene.String()
    description = graphene.String()


class ModifierGroup(graphene.ObjectType):
    group = graphene.String()
    description = graphene.String()
    modifiers = graphene.List(Modifier)


def get_modifier_groups():
    modifier_items = PromptModifiers.list()
    grouped = {}
    docstrings = {}

    for item in modifier_items:
        full_path = item["key"]
        group = item["group"]
        name = item["name"]
        description = item["description"]
        grouped.setdefault(group, []).append({
            "key": full_path,
            "name": name,
            "group": group,
            "description": description,
        })

    for group in grouped:
        try:
            module = importlib.import_module(f"simai.prompts.builtins._{group.lower()}")
            docstrings[group] = (module.__doc__ or "").strip()
        except Exception:
            docstrings[group] = ""

    for mods in grouped.values():
        mods.sort(key=lambda m: m["description"].lower())

    return [
        {
            "group": group,
            "description": docstrings[group],
            "modifiers": mods
        }
        for group, mods in sorted(grouped.items(), key=lambda item: item[0].lower())
    ]


class Query(graphene.ObjectType):
    modifier = graphene.Field(Modifier, key=graphene.String(required=True))
    all_modifiers = graphene.List(Modifier)

    modifier_group = graphene.Field(ModifierGroup, group=graphene.String(required=True))
    modifier_groups = graphene.List(ModifierGroup, groups=graphene.List(graphene.String))

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

    def resolve_all_modifiers(root, info, group=None):
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
            result.append(Modifier(
                key=item["key"],
                name=item["name"],
                group=item["group"],
                description=description,
            ))
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