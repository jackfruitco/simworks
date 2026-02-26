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

from typing import Optional

# Modifier group definitions
# Format: group_name -> {description, modifiers: [{key, description}]}
MODIFIER_GROUPS = {
    "ClinicalScenario": {
        "description": "Type of clinical encounter",
        "modifiers": [
            {
                "key": "emergency",
                "description": "Emergency/trauma scenario",
            },
            {
                "key": "outpatient",
                "description": "Outpatient clinic visit",
            },
            {
                "key": "inpatient",
                "description": "Inpatient hospital admission",
            },
        ],
    },
    "ClinicalDuration": {
        "description": "Simulation time constraints",
        "modifiers": [
            {
                "key": "short_encounter",
                "description": "Short encounter (5-10 minutes)",
            },
            {
                "key": "standard_encounter",
                "description": "Standard encounter (15-20 minutes)",
            },
            {
                "key": "extended_encounter",
                "description": "Extended encounter (30+ minutes)",
            },
        ],
    },
    "Feedback": {
        "description": "Feedback mode options",
        "modifiers": [
            {
                "key": "immediate_feedback",
                "description": "Provide feedback during simulation",
            },
            {
                "key": "post_feedback",
                "description": "Provide feedback after simulation ends",
            },
        ],
    },
}


def get_modifier_groups(groups: Optional[list[str]] = None) -> list[dict]:
    """
    Get modifier groups, optionally filtered by group names.

    Args:
        groups: Optional list of group names to filter. If None, returns all groups.

    Returns:
        List of modifier group dicts with 'group', 'description', and 'modifiers' keys.
    """
    if groups is None:
        group_names = list(MODIFIER_GROUPS.keys())
    else:
        group_names = groups

    result = []
    for group_name in group_names:
        if group_name in MODIFIER_GROUPS:
            group_data = MODIFIER_GROUPS[group_name]
            result.append({
                "group": group_name,
                "description": group_data["description"],
                "modifiers": group_data["modifiers"],
            })

    return result


def get_modifier(key: str) -> Optional[dict]:
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
