import graphene
from simai.prompts import PromptModifiers
import importlib


class Modifier(graphene.ObjectType):
    key = graphene.String()
    description = graphene.String()
    value = graphene.String()


class ModifierGroup(graphene.ObjectType):
    group = graphene.String()
    description = graphene.String()
    modifiers = graphene.List(Modifier)


def get_modifier_groups():
    modifier_items = PromptModifiers["list"]()
    grouped = {}
    docstrings = {}

    for full_path, func in modifier_items:
        group = full_path.split(".")[0]
        description = func.__doc__.strip().split("\n")[0] if func.__doc__ else full_path
        grouped.setdefault(group, []).append({
            "key": full_path,
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


# 🔹 GraphQL Root Query
class Query(graphene.ObjectType):
    modifier = graphene.Field(Modifier, key=graphene.String(required=True))
    all_modifiers = graphene.List(Modifier)

    modifier_group = graphene.Field(ModifierGroup, group=graphene.String())
    all_modifier_groups = graphene.List(ModifierGroup)

    def resolve_modifier(root, info, key):
        func = PromptModifiers["get"](key)
        if not func:
            return None
        description = func.__doc__.strip().split("\n")[0] if func.__doc__ else key
        value = func()
        return Modifier(key=key, description=description, value=value)

    def resolve_all_modifiers(root, info):
        modifier_items = PromptModifiers["list"]()
        result = []
        for key, func in modifier_items:
            description = func.__doc__.strip().split("\n")[0] if func.__doc__ else key
            try:
                value = func()
            except Exception:
                value = None  # Or a fallback string like "<requires user/role>"
            result.append(Modifier(key=key, description=description, value=value))
        return result

    def resolve_modifier_group(root, info, group):
        grouped = get_modifier_groups()
        normalized = group.lower()
        for g in grouped:
            if g["group"] == normalized:
                return g
        return None

    def resolve_all_modifier_groups(root, info):
        grouped = get_modifier_groups()
        return grouped

class Mutation(graphene.ObjectType):
    pass