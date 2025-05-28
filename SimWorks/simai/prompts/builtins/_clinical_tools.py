# SimWorks/simai/prompts/builtins/_clinical_scenario.py
"""PromptModifiers that enable users to order clinical tools (e.g., labs) for a simulation."""

from simai.prompts.registry import register_modifier
from simcore.models import Simulation

_BASE = f"""
For this prompt only, you are acting as the simulation facilitator.

The user has requested requested clinical tools, such as labs and radiology.
For each tool requested, you should provide the standardized name using lab 
and radiology standard abbreviations or order sentences. You should provide the
standard reference range for all labs, and include a flag for normal or abnormal 
values. 
"""

@register_modifier("ClinicalTools.PatientScenarioData")
def patient_scenario_data(simulation: Simulation | int) -> str:
    """
    Returns string for a(n) Patient Scenario Data modifier.

    This is used to prep the AI model to return clinically relevant results."

    :param simulation: The Simulation object or primary key (int) for which to generate the patient scenario data.

    :raises ValueError: If the provided simulation is not a Simulation instance or does not exist.
    :raises TypeError: If the provided simulation is not an int or Simulation instance.
    :raises AttributeError: If the provided simulation does not have a metadata attribute.

    :return: A string containing the patient scenario data.
    """
    if not isinstance(simulation, Simulation):
        try:
            simulation = Simulation.objects.get(pk=simulation)
        except ValueError:
            raise ValueError(
                f"simulation must be a Simulation instance or a valid primary key (was provided: {simulation})."
            )
        except Simulation.DoesNotExist:
            raise ValueError(f"Simulation with pk {simulation} not found.")

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
        gender_meta = simulation.metadata.get(key="gender")
        sex = f"The patient's sex is {gender_meta.value}."
    except Simulation.metadata.model.DoesNotExist:
        pass

    try:
        age_meta = simulation.metadata.get(key="age")
        age = f"The patient's age is {age_meta.value}."
    except Simulation.metadata.model.DoesNotExist:
        pass

    info_parts = [dx, cc, sex, age]
    info_string = " ".join(filter(None, info_parts))

    return f"{info_string} {_base}"

@register_modifier("ClinicalTools.GenericLab")
def clinical_tools_generic_lab(lab_order: str | list[str], **extra_kwargs):
    """Returns string for a(n) Lab clinical scenario modifier."""
    if not isinstance(lab_order, list):
        lab_order = [lab_order]

    if not all(isinstance(item, str) for item in lab_order):
        raise ValueError("lab_order must be a string or a list of strings.")

    return f"{_BASE} The user has requested the following labs: {', '.join(lab_order.upper())}."