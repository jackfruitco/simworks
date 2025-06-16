"""
This module provides an asynchronous client for interacting with the OpenAI API
to facilitate patient simulations in a chat environment. It includes functions
to build payloads for patient replies and introductions, and a service class
to generate responses using the OpenAI model.
"""
import inspect
import logging
import mimetypes
from typing import List
from typing import Optional

from asgiref.sync import sync_to_async
from django.conf import settings
from openai import AsyncOpenAI

from chatlab.models import Message
from simcore.models import Simulation
from .models import ResponseType
from .openai_gateway import process_response
from .output_schemas import message_schema, feedback_schema, patient_results_schema
from .prompts import Prompt

logger = logging.getLogger(__name__)

@sync_to_async
def build_patient_initial_payload(simulation: Simulation) -> List[dict]:
    """
    Build the initial payload for the patient's introduction in the simulation.

    Args:
        simulation (Simulation): The simulation object containing prompt and patient information.

    Returns:
        List[dict]: A list of dictionaries representing the role and content for the introduction.
    """

    instruction = simulation.prompt
    instruction += (
        f"\n\nYour name is {simulation.sim_patient_full_name}. "
        f"Stay in character as {simulation.sim_patient_full_name} and respond accordingly."
    )
    return [
        {"role": "developer", "content": instruction},
        {"role": "user", "content": "Begin."},
    ]


@sync_to_async
def build_patient_reply_payload(user_msg: Message) -> dict:
    """
    Build the payload for the patient's reply to be sent to OpenAI.

    Args:
        user_msg (Message): The user's message object containing the previous response ID and input.

    Returns:
        dict: A dictionary containing the previous response ID and user input.
    """
    return {
        "previous_response_id": user_msg.simulation.get_previous_response_id() or None,
        "input": [
            user_msg.get_openai_input(),
            # {"role": "user", "content": "content"},
        ],
    }

@sync_to_async
def build_feedback_payload(simulation: Simulation) -> dict:
    """
    Build the payload for AI feedback after the simulation has ended.

    Args:
        simulation (Simulation): The simulation object to reference the last AI message from.

    Returns:
        dict: A dictionary containing the previous response ID and developer/user input.
    """
    # instructions = build_prompt("Feedback.endex", include_default=False)

    # Build prompt
    instructions = Prompt.build(
        "Feedback.endex",
        simulation=simulation,
        include_default=False,
    )

    return {
        "previous_response_id": simulation.get_previous_response_id() or None,
        "input": [
            {"role": "developer", "content": instructions},
            {"role": "user", "content": "Provide feedback to the user"},
        ],
    }

async def build_patient_results_payload(simulation: Simulation, lab_order: str | list[str]) -> dict:
    """
    Build the payload for AI-determined patient results.

    :param simulation: Simulation object or int (simulation pk)
    :param lab_order: str or list[str]
    :return: dict: A dictionary containing the previous response ID and developer/user input.
    """
    previous_response_id = await simulation.aget_previous_response_id() or None
    instructions = await Prompt.abuild(
        "ClinicalResults.PatientScenarioData",
        "ClinicalResults.GenericLab",
        include_default=False,
        lab_order=lab_order,
        simulation=simulation,
    )
    return {
        "previous_response_id": previous_response_id,
        "input": [
            {"role": "developer", "content": instructions},
            {"role": "user", "content": f"New Patient Orders: {lab_order}"},
        ],
    }


# noinspection PyTypeChecker
class SimAIClient:
    """
    A service class to interact with the OpenAI API for generating patient replies
    and introductions in the context of simulations.
    """

    def __init__(self, model: Optional[str] = None):
        """
        Initialize the OpenAI chat service with a specified model.

        Args:
            model (Optional[str]): The OpenAI model to use; defaults to the model specified in settings.
        """
        self.model = model or getattr(settings, "OPENAI_MODEL", "gpt-4")
        self.client = AsyncOpenAI()  # Initialize the OpenAI client

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @staticmethod
    async def log(func_name, msg="triggered", level=logging.DEBUG) -> None:
        return logger.log(level, f"[{func_name}]: {msg}")

    async def generate_patient_initial(
        self, simulation: Simulation, stream: bool = False
    ) -> List[Message]:
        """
        Generate the initial introduction message for the patient in the simulation.

        Args:
            simulation (Simulation): The simulation object.
            stream (bool): If the feedback should be streamed.

        Returns:
            List[Message]: A list of Message objects representing the initial introduction.
        """
        func_name = inspect.currentframe().f_code.co_name

        # Get output schema as `content`, and input_payload (prompt, message)
        text = await message_schema(initial=True)
        input_payload = await build_patient_initial_payload(simulation)

        response = await self.client.responses.create(
            model=self.model,
            input=input_payload,
            text=text,
            stream=stream,
        )

        return await process_response(response, simulation, stream)

    async def generate_patient_reply(
        self, user_msg: Message, stream: bool = False
    ) -> List[Message]:
        """
        Generate a reply from the patient based on the user's message.

        Args:
            user_msg (Message): The user's message object.
            stream (bool): If the feedback should be streamed.

        Returns:
            List[Message]: A list of Message objects representing the patient's reply.
        """
        func_name = inspect.currentframe().f_code.co_name
        await self.log(
            func_name=func_name,
            msg=f"Requesting SimMessage for Sim#{user_msg.simulation.pk} "
            f"in response to {user_msg.sender}'s input (ID: {user_msg.id})...",
            level=logging.INFO,
        )

        # Build payload (prompt, instructions), then get the response from OpenAI
        payload = await build_patient_reply_payload(user_msg)
        text = await message_schema()
        response = await self.client.responses.create(
            model=self.model,
            text=text,
            stream=stream,
            **payload,
        )

        simulation = user_msg.simulation
        return await process_response(response, simulation, stream)

    async def generate_simulation_feedback(
        self, simulation: Simulation, stream: bool = False
    ) -> List[Message]:
        """
        Generate feedback for the user at the completion of the simulation.

        Args:
            simulation (Simulation): The simulation object.
            stream (bool): If the feedback should be streamed.

        Returns:
            List[Message]: A list of Message objects representing the AI-generated feedback.
        """
        payload = await build_feedback_payload(simulation)
        text = await feedback_schema()
        response = await self.client.responses.create(
            model=self.model,
            text=text,
            stream=stream,
            **payload,
        )

        return await process_response(response, simulation, stream, response_type=ResponseType.FEEDBACK)

    # noinspection PyTypeChecker
    async def generate_patient_reply_image(
            self,
            *modifiers,
            simulation: Simulation | int = None,
            output_format="webp",
            include_default=False,
            **kwargs
    ) -> List[Message]:
        """
        Generate a patient image for a given simulation using OpenAI Image API.
        """
        func_name = inspect.currentframe().f_code.co_name
        logger.debug(f"[{func_name}] triggered...")

        # Get simulation instance if provided as int
        if isinstance(simulation, int):
            simulation = await Simulation.objects.aget(id=simulation)

        logger.info(f"starting image generation image for Sim{simulation.pk}...")

        # Clean & validate output format
        # See https://platform.openai.com/docs/api-reference/images/create#images-create-output_format
        OPENAI_VALID_FORMATS = {"png", "jpeg", "webp"}
        output_format = output_format.lower().strip()
        if output_format not in OPENAI_VALID_FORMATS:
            raise ValueError(
                f"Unsupported output_format: {output_format} "
                f"(must be one of {OPENAI_VALID_FORMATS})"
            )

        # Build prompt
        prompt = await Prompt.abuild(
            "Image.PatientImage",
            *modifiers,
            simulation=simulation,
            include_default=include_default,
            **kwargs,
        )

        # Call OpenAI API Images API
        # See https://platform.openai.com/docs/api-reference/images
        try:
            response = await self.client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                n=1,
                size="1024x1024",
                output_format=output_format,
                output_compression=70,
            )
        except Exception as e:
            logger.error(f"[{func_name}] OpenAI image generation failed: {e}")
            return e

        return await process_response(
            response=response,
            simulation=simulation,
            stream=False,
            response_type=ResponseType.MEDIA,
            mime_type=mimetypes.guess_file_type(f"image.{output_format}")[0] or "image/webp"
        )

    async def generate_patient_results(
            self,
            *modifiers,
            simulation: Simulation | int = None,
            lab_orders: str | list[str] = None,
            include_default=False,
            stream: bool = False,
            **kwargs
    ) -> List[Message]:
        """
        Generate patient results for requested labs or radiology using OpenAI Image API.
        """
        func_name = inspect.currentframe().f_code.co_name
        logger.debug(f"[{func_name}] triggered...")

        # Resolve simulation instance
        # Allows for sim to be passed as int or Simulation object
        if isinstance(simulation, int):
            simulation = await Simulation.objects.aget(id=simulation)

        logger.info(f"starting lab result generation for Sim{simulation.pk}...")

        text = await patient_results_schema()
        payload = await build_patient_results_payload(simulation, lab_orders)
        response = await self.client.responses.create(
            model=self.model,
            text=text,
            stream=stream,
            **payload,
        )

        return await process_response(
            response,
            simulation,
            stream,
            response_type=ResponseType.PATIENT_RESULTS,
        )