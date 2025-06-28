# SimWorks/simai/prompts/builtins/_clinical_scenario.py
"""PromptModifiers that modify the clinical scenario of a simulation."""
from simai.prompts.registry import register_modifier

_BASE = "The patient's complaint and diagnosis should correlate to the following:"


@register_modifier("ClinicalScenario.MSK", "prefer musculoskeletal scenario")
def clinical_scenario_msk(user=None, role=None, **kwargs):
    """Returns string for a(n) Musculoskeletal clinical scenario modifier."""
    return f"{_BASE} MSK (musculoskeletal injuries)."


@register_modifier("ClinicalScenario.RESP", "prefer respiratory system scenario")
def clinical_scenario_resp(user=None, role=None, **kwargs):
    """Returns string for a(n) Respiratory System clinical scenario modifier."""
    return f"{_BASE} Respiratory System."


@register_modifier("ClinicalScenario.VIRUS", "prefer viral infection scenario")
def clinical_scenario_virus(user=None, role=None, **kwargs):
    """Returns string for a(n) Viral Infection clinical scenario modifier."""
    return f"{_BASE} Viral infections."


@register_modifier("ClinicalScenario.BACT", "prefer bacterial infection scenario")
def clinical_scenario_bact(user=None, role=None, **kwargs):
    """Returns string for a(n) Bacterial Infection clinical scenario modifier."""
    return f"{_BASE} Bacterial infections."


@register_modifier("ClinicalScenario.DERM", "prefer dermatology scenario")
def clinical_scenario_derm(**kwargs):
    """Returns string for a(n) Dermatology clinical scenario modifier."""
    return f"{_BASE} Dermatology conditions, skin conditions, rashes, etc."
