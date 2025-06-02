# SimWorks/simai/prompts/builtins/_clinical_results.py
"""PromptModifiers that enable users to request clinical results (e.g., labs) for a simulation."""
from asgiref.sync import sync_to_async

from simai.prompts.registry import register_modifier
from simcore.models import Simulation, SimulationMetadata

_BASE = f"""
For this prompt only, you are acting as the simulation facilitator.

The user has requested requested clinical orders, such as labs and radiology.
For each order requested, you should provide the standardized name using lab 
and radiology standard abbreviations or order sentences. You should provide the
standard reference range for all labs, and include a flag for normal or abnormal 
values. 
"""

@register_modifier("ClinicalResults.PatientScenarioData")
async def patient_scenario_data(simulation: Simulation, **kwargs) -> str:
    """
    Returns string for a(n) Patient Scenario Data modifier.

    This is used to prep the AI model to return clinically relevant results.

    :param simulation: The Simulation object for which to generate the patient scenario data.

    :raises ValueError: If the provided simulation is not a Simulation instance or does not exist.
    :raises TypeError: If the provided simulation is not an int or Simulation instance.
    :raises AttributeError: If the provided simulation does not have a metadata attribute.

    :return: A string containing the patient scenario data.
    """
    if not isinstance(simulation, Simulation):
        raise TypeError("simulation must be a Simulation instance.")

    _base = (
        "Ensure the values are in the correct units, and clinically "
        "correlate with the clinical scenario, diagnosis, and complaints."
    )

    dx = f"The patient's diagnosis is {simulation.diagnosis}." if simulation.diagnosis else ""
    cc = f"The patient's chief complaint is {simulation.chief_complaint}." if simulation.chief_complaint else ""

    # Default to empty strings in case metadata is missing
    sex = ""
    age = ""

    try:
        gender_meta = await sync_to_async(simulation.metadata.get)(key="gender")
        sex = f"The patient's sex is {gender_meta.value}."
    except SimulationMetadata.DoesNotExist:
        pass

    try:
        age_meta = await sync_to_async(simulation.metadata.get)(key="age")
        age = f"The patient's age is {age_meta.value}."
    except SimulationMetadata.DoesNotExist:
        pass

    info_parts = [dx, cc, sex, age]
    info_string = " ".join(filter(None, info_parts))

    return f"{info_string} {_base}"

@register_modifier("ClinicalResults.GenericLab")
async def generic_lab(lab_order: str | list[str], **kwargs):
    """Returns string for a(n) Lab clinical scenario modifier."""
    if not isinstance(lab_order, list):
        lab_order = [lab_order]

    if not all(isinstance(item, str) for item in lab_order):
        raise ValueError("lab_order must be a string or a list of strings.")

    return f"{_BASE} The user has requested the following labs: {', '.join(lab_order).upper()}."