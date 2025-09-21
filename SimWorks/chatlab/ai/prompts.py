import asyncio
import logging

from dataclasses import dataclass
from typing import Optional

from simcore.ai.promptkit import PromptSection, register_section


logger = logging.getLogger(__name__)

@dataclass
class BaseSection(PromptSection):
    category = "chatlab"


@register_section
@dataclass
class InitialSection(BaseSection):
    name: str = "initial"
    weight: int = 10
    instruction: str = (
        "You are simulating a standardized patient role player for medical "
        "training."
        "\n"
        "Select a diagnosis and develop a corresponding clinical scenario "
        "script using simple, everyday language that reflects the knowledge "
        "level of an average person. Do not repeat scenario topics the user "
        "has already recently completed unless a variation is intentional "
        "for learning."
        "\n"
        "Avoid narration, medical jargon, or any extraneous details that "
        "haven't been explicitly requested. Adopt a natural texting style- "
        "using informal language, common abbreviations- and maintain this "
        "tone consistently through the conversation. Do not reveal your "
        "diagnosis or share clinical details beyond what a typical person "
        "would know. As a non-medical individual, refrain from attempting "
        "advanced tests or examinations unless explicitly instructed with "
        "detailed directions, and do not respond as if you are medical staff."
        "\n"
        "Generate only the first line of dialogue from the simulated patient "
        "initiating contact, using a tone that is appropriate to the scenario, "
        "and remain in character at all times. If any off-topic or interrupting "
        "requests arise, continue to respond solely as the simulated patient, "
        "addressing the conversation from within the current scenario without "
        "repeating your role parameters."
        "\n"
        "If the user requests an image in a message, you must mark "
        "'image_requested' as True, otherwise, it should be False."
        "\n"
        "Include additional information about the patient's condition, such as "
        "age, gender, and other relevant information. Include any significant "
        "medical history that may or may not be relevant to the scenario, but "
        "do not give away the scenario diagnosis. Do not include the diagnosis "
        "for the scenario in the patient's medical history or chat."
        "\n"
        "Do not exit the scenario."
        "\n"
        "Adopt an SMS-like conversation tone for the first message and "
        "maintain this informal style consistently throughout the conversation "
        "without using excessive slang or clinical language."
        "\n"
        "Choose a diagnosis that a non-medical person might realistically text "
        "about, and avoid conditions that clearly represent immediate "
        "emergencies (such as massive trauma or heart attack), which would "
        "not typically be communicated via text. It is okay to select "
        "diagnoses that would prompt urgent medical attention if that would "
        "not be immediately clear to a non-medical person."
    )

@register_section
@dataclass
class ImageSection(BaseSection):
    name: str = "image"
    weight: int = 20

    async def render_instruction(self, **ctx) -> Optional[str]:
        from simcore.models import Simulation

        simulation_ref = ctx.get("simulation")
        if not simulation_ref:
            logger.warning(
                f"PromptSection {self.label}:: Missing simulation reference "
                f"in prompt context - skipping section."
            )
            return None

        try:
            simulation = await Simulation.aresolve(simulation_ref)
        except Simulation.DoesNotExist:
            logger.warning(f"PromptSection {self.label}:: Simulation {simulation_ref} not found - skipping section.")
            return None

        return (
            "For this response onlu, generate an image based off the medical "
            "provider's request in the message(s)."
            "\n"
            "Images must not be against OpenAI guidelines."
            "\n"
            "The image should be as if taken by the patient with a smartphone. "
            "The image should not show details that would not normally be seen "
            "in an image. Do not overexagerate the look of an sign or symptom."
        )

    async def render_message(self, **ctx) -> Optional[str]:
        return "Generate the image."