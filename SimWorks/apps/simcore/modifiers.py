# simcore/modifiers.py
"""Simulation modifier configuration.

Modifiers allow customization of simulation scenarios. They are grouped
by category and can be selected when creating a new simulation.

Usage:
    from apps.simcore.modifiers import get_modifier_groups, get_modifier

    # Get all modifier groups
    groups = get_modifier_groups()

    # Get specific groups
    groups = get_modifier_groups(["ClinicalScenario", "ClinicalDuration"])

    # Get a specific modifier
    modifier = get_modifier("short_encounter")
"""

# Modifier group definitions
# Format: group_name -> {description, modifiers: [{key, description}]}
MODIFIER_GROUPS = {
    "Environment": {
        "description": "Type of clinical encounter",
        "modifiers": [
            {
                "key": "musculoskeletal",
                "description": "musculoskeletal injury or issue scenario",
            },
            {
                "key": "respiratory",
                "description": "respiratory issue",
            },
            {
                "key": "dermatologic",
                "description": "dermatology issue/illness",
            },
        ],
    },
    "ClinicalDuration": {
        "description": "Simulation time constraints",
        "modifiers": [
            {
                "key": "acute",
                "description": "New concerns beginning within last 4 weeks",
            },
            {
                "key": "subacute",
                "description": "Concerns within the last 4-8 weeks",
            },
            {
                "key": "chronic",
                "description": "Concerns beginning over 8 weeks ago",
            },
        ],
    },
}


def get_modifier_groups(groups: list[str] | None = None) -> list[dict]:
    """
    Get modifier groups, optionally filtered by group names.

    Args:
        groups: Optional list of group names to filter. If None, returns all groups.

    Returns:
        List of modifier group dicts with 'group', 'description', and 'modifiers' keys.
    """
    group_names = list(MODIFIER_GROUPS.keys()) if groups is None else groups

    result = []
    for group_name in group_names:
        if group_name in MODIFIER_GROUPS:
            group_data = MODIFIER_GROUPS[group_name]
            result.append(
                {
                    "group": group_name,
                    "description": group_data["description"],
                    "modifiers": group_data["modifiers"],
                }
            )

    return result


def get_modifier(key: str) -> dict | None:
    """
    Get a specific modifier by key.

    Args:
        key: The modifier key to look up.

    Returns:
        The modifier dict if found, None otherwise.
    """
    for group_data in MODIFIER_GROUPS.values():
        for modifier in group_data["modifiers"]:
            if modifier["key"] == key:
                return modifier
    return None
