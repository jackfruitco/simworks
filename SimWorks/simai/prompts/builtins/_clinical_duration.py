# SimWorks/simai/prompts/builtins/_clinical_scenario.py
"""PromptModifiers that modify the clinical duration of a simulation (i.e. Acute, Chronic, etc.)."""

from simai.prompts.registry import register_modifier

_BASE = "The duration for the clinical scenario :"


@register_modifier("ClinicalDuration.Acute")
def clinical_duration_acute(**kwargs):
    """Returns string for a(n) acute clinical scenario modifier."""
    return f"{_BASE} Acute (new injury/illness within last 72-hours or so)."


@register_modifier("ClinicalDuration.SubAcute")
def clinical_duration_subacute(**kwargs):
    """Returns string for a(n) sub-acute clinical scenario modifier."""
    return f"{_BASE} Sub-Acute (new injury/illness within last 1-3 weeks)."


@register_modifier("ClinicalDuration.Chronic")
def clinical_duration_chronic(**kwargs):
    """Returns string for a(n) chronic clinical scenario modifier."""
    return f"{_BASE} Chronic (injury/illness lasting greater than 3 weeks)."
