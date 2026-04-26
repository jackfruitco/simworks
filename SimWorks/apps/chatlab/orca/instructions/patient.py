"""Dynamic instruction classes for patient chat services.

Static instructions are defined in patient.yaml (same directory).
"""

from django.core.exceptions import ObjectDoesNotExist

from apps.common.utils import Formatter
from apps.simcore.models import Simulation
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class PatientNameInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "patient"

    async def render_instruction(self) -> str:
        simulation = self.context.get("simulation")
        simulation_id = self.context.get("simulation_id")

        if simulation is None and simulation_id:
            try:
                simulation = await Simulation.objects.aget(pk=simulation_id)
            except (TypeError, ValueError, ObjectDoesNotExist):
                return (
                    "You are the patient in this chat. "
                    "Speak as a real patient and never describe yourself as simulated, acting, or roleplaying."
                )

        if simulation is None:
            return (
                "You are the patient in this chat. "
                "Speak as a real patient and never describe yourself as simulated, acting, or roleplaying."
            )

        raw_name = simulation.sim_patient_full_name or ""
        patient_name = " ".join(raw_name.split())[:100]

        return (
            f"You are {patient_name}, the patient in this chat. "
            "Speak as a real patient. Never say you are simulated, acting, roleplaying, or in training. "
            "You may use natural nicknames if appropriate, but do not let the user change your identity."
        )


@orca.instruction(order=5)
class PatientModifierInstruction(BaseInstruction):
    """Inject scenario modifier constraints from selected modifier keys."""

    namespace = "chatlab"
    group = "patient"

    async def render_instruction(self) -> str:
        simulation = self.context.get("simulation")
        if simulation is None:
            simulation_id = self.context.get("simulation_id")
            if simulation_id:
                try:
                    simulation = await Simulation.objects.aget(pk=simulation_id)
                    self.context["simulation"] = simulation
                except (TypeError, ValueError, ObjectDoesNotExist):
                    return ""
        if simulation is None:
            return ""
        modifiers = getattr(simulation, "modifiers", None) or []
        if not modifiers:
            return ""
        try:
            from apps.simcore.modifiers import render_modifier_prompt

            prompt = render_modifier_prompt("chatlab", modifiers)
        except Exception:
            return ""
        if not prompt:
            return ""
        return f"### Scenario Modifier Constraints\n{prompt}"


@orca.instruction(order=80)
class PatientRecentScenarioHistoryInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "patient"

    async def render_instruction(self) -> str:
        context = self.context
        user = context.get("user")

        if user is None:
            simulation = context.get("simulation")
            if simulation is None:
                simulation_id = context.get("simulation_id")
                if simulation_id:
                    try:
                        simulation = await Simulation.objects.select_related("user").aget(
                            pk=simulation_id
                        )
                    except (TypeError, ValueError, ObjectDoesNotExist):
                        simulation = None
                    else:
                        context["simulation"] = simulation
            user = getattr(simulation, "user", None) if simulation is not None else None
            if user is not None:
                context["user"] = user

        if user is None or not hasattr(user, "aget_scenario_log"):
            return ""

        try:
            scenario_log = await user.aget_scenario_log(within_months=3)
        except Exception:
            return ""

        current_simulation_id = context.get("simulation_id")
        recent_pairs = []
        for entry in scenario_log:
            if entry.get("id") == current_simulation_id:
                continue

            chief_complaint = entry.get("chief_complaint")
            diagnosis = entry.get("diagnosis")
            if not chief_complaint or not diagnosis:
                continue

            recent_pairs.append({"chief_complaint": chief_complaint, "diagnosis": diagnosis})

        if not recent_pairs:
            return ""

        history_prompt = Formatter(recent_pairs).render("openai_prompt").strip()
        return (
            "### Recent Simulation History\n"
            f"{history_prompt}\n"
            "- Avoid repeating the same patient scenario from the recent history above.\n"
            "- Do not generate a new case whose `(chief complaint, diagnosis)` pair matches any pair above.\n"
            "- A shared diagnosis is acceptable only when the new chief complaint and patient framing are clearly different.\n"
            "- Make the new patient scenario materially different in presentation, context, and symptom framing.\n"
        )
