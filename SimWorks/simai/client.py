"""
This module provides an asynchronous client for interacting with the OpenAI API
to facilitate patient simulations in a chat environment. It includes functions
to build payloads for patient replies and introductions, and a service class
to generate responses using the OpenAI model.

TODO: Remove deprecated `self.log(...)` usages
TODO: Implement `_get_raw_response` and `get_response` methods
TODO: Move custom methods other than those above out of the client
"""

import inspect
import logging
import mimetypes
import warnings
from typing import List
from typing import Optional
from typing import Union

from asgiref.sync import sync_to_async
from openai.types.responses import (Response as OpenAIResponse,
                                    ResponseTextConfigParam)

from chatlab.models import Message
from django.conf import settings
from openai import AsyncOpenAI

from simcore.ai.utils.helpers import build_response_text_param
from simcore.ai.utils.validation import validate_image_format
from simcore.models import LabResult
from simcore.models import RadResult
from simcore.models import Simulation
from simcore.models import SimulationMetadata

from .models import ResponseType
from .openai_gateway import process_response
from .output_schemas import feedback_schema
from .structured_output import PatientInitialSchema
from .structured_output import PatientReplySchema
from .structured_output import PatientResultsSchema
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

    prompt = simulation.prompt
    prompt += (
        f"\n\nYour name is {simulation.sim_patient_full_name}. "
        f"Stay in character as {simulation.sim_patient_full_name} and respond accordingly."
    )
    return [
        {"role": "developer", "content": prompt},
        {"role": "user", "content": ""},
    ]


@sync_to_async
def build_patient_reply_payload(user_msg: Message, image_generation: bool = False) -> dict:
    """
    Build the payload for the patient's reply to be sent to OpenAI.

    :param user_msg: The user's content object containing the previous response ID and input.
    :type user_msg: Message

    :param image_generation: Whether to generate an image or not. Defaults to False.
    :type image_generation: bool, optional

    :return: A dictionary containing the previous response ID and user input.
    :rtype: dict
    """
    _previous_response_id = user_msg.simulation.get_previous_response_id() or None
    _input = [user_msg.get_openai_input() or None]

    # Add developer prompt if image generation is enabled
    if image_generation:
        _prompt = Prompt.build(
            "Image.PatientImage",
            simulation=user_msg.simulation,
            include_default=False,
        )

        _input.append(
            {
                "role": "developer",
                "content": _prompt,
            }
        )

    return {
        "previous_response_id": _previous_response_id,
        "input": _input,
    }


@sync_to_async
def build_feedback_payload(simulation: Simulation) -> dict:
    """
    Build the payload for AI feedback after the simulation has ended.

    Args:
        simulation (Simulation): The simulation object to reference the last AI content from.

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


async def build_patient_results_payload(
    simulation: Simulation, lab_order: str | list[str]
) -> dict:
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
        warnings.warn(
            "this logger util is deprecated. Use direct logging instead.",
            PendingDeprecationWarning,
            stacklevel=2,
        )
        return logger.log(level, f"[{func_name}]: {msg}")

    async def _get_raw_response(
            self,
    ) -> OpenAIResponse:
        pass

    async def get_response(
            self,
    ) -> OpenAIResponse:
        pass

    async def generate_patient_initial(
        self, simulation: Simulation | int, stream: bool = False
    ) -> tuple[list[Message], list[SimulationMetadata]]:
        """
        Generate the initial introduction message for the patient in the simulation.

        Args:
            simulation (Simulation): The simulation object.
            stream (bool): If the feedback should be streamed.

        Returns:
            tuple: A tuple containing a list of Message objects representing
            the patient's introduction and a list of SimulationMetadata objects.
        """
        func_name = inspect.currentframe().f_code.co_name

        # Resolve Simulation instance to allow int to be passed
        simulation = await Simulation.aresolve(simulation)

        # Build output schema (`text` param) and input_payload (`input` param)
        text: ResponseTextConfigParam = build_response_text_param(PatientInitialSchema)
        input_payload = await build_patient_initial_payload(simulation)

        response: OpenAIResponse = await self.client.responses.create(
            model=self.model,
            input=input_payload,
            text=text,
            stream=stream,
        )

        # Process Response, and return a tuple with a list of Messages and Metadata
        _messages, _metadata = await process_response(response, simulation, stream)
        return _messages, _metadata

    async def generate_patient_reply(
        self, user_msg: Message, stream: bool = False
    ) -> tuple[list[Message], list[SimulationMetadata]]:
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
        text: ResponseTextConfigParam = build_response_text_param(PatientReplySchema)
        response = await self.client.responses.create(
            model=self.model,
            text=text,
            stream=stream,
            **payload,
        )

        simulation = user_msg.simulation

        # Process Response, and return a tuple with a list of Messages and Metadata
        _messages, _metadata = await process_response(response, simulation, stream)
        return _messages, _metadata

    async def generate_simulation_feedback(
        self, simulation: Simulation | int, stream: bool = False
    ) -> tuple[list[Message], list[SimulationMetadata]]:
        """
        Generate feedback for the user at the completion of the simulation.

        Args:
            simulation (Simulation): The simulation object.
            stream (bool): If the feedback should be streamed.

        Returns:
            List[Message]: A list of Message objects representing the AI-generated feedback.
        """
        # Get the simulation instance if provided an int
        simulation = await Simulation.aresolve(simulation)

        payload = await build_feedback_payload(simulation)
        text = await feedback_schema()
        response = await self.client.responses.create(
            model=self.model,
            text=text,
            stream=stream,
            **payload,
        )

        # Process Response, and return a tuple with a list of Messages and Metadata
        _messages, _metadata = await process_response(
            response, simulation, stream, response_type=ResponseType.FEEDBACK
        )
        return _messages, _metadata

    async def generate_patient_image(
        self,
        *modifiers,
        simulation: Simulation | int = None,
        user_msg: Message = None,
        _stream: bool = False,
        _format="webp",
        _include_default=False,
        **kwargs,
    ) -> tuple[list[Message], list[SimulationMetadata]]:
        """
        Generate a patient image for a given simulation using OpenAI Response API with Image Generation.
        :param modifiers:
        :param simulation: The Simulation instance or int (pk)
        :param user_msg: The Message instance for the user's input (optional)
        :param _stream: Whether to stream the OpenAI Response or not
        :param _format: The format of the image to generate. Defaults to "webp"
        :param _include_default: Whether to include the default prompt or not. Defaults to False.
        :param kwargs:
        :return:
        """
        # Ensure either user_msg or simulation is provided
        if user_msg is None and simulation is None:
            raise ValueError("Must provide either user_msg or simulation")

        # Get the simulation instance if provided as int
        simulation = await Simulation.aresolve(
            simulation if simulation is not None else user_msg.simulation
        )

        # Get the last content from the simulation if user_msg is not provided
        if user_msg is None:
            user_msg = await simulation.messages.alast()

        logger.info(f"starting image generation image (simulation id: {simulation.pk})...")

        # Validate the provided image format
        # See https://platform.openai.com/docs/api-reference/images/create#images-create-output_format
        try:
            _format = validate_image_format(_format)
        except ValueError as e:
            from django.conf import settings
            _default_format = settings.DEFAULT_IMAGE_FORMAT
            logger.warning(f"Invalid image format: `{_format}`. Using default instead: `{_default_format}`")
            _format = _default_format

        # Build payload including previous_response_id and input
        payload = await build_patient_reply_payload(user_msg, image_generation=True)


        try:
            response = await self.client.responses.create(
                model=self.model,
                stream=_stream,
                tools=[{"type": "image_generation"}],
                **payload
            )
        except Exception as e:
            raise f"Image Generation failed: {e}"

        # Process Response, and return a tuple with a list of Messages and Metadata
        _messages, _metadata = await process_response(
            response=response,
            simulation=simulation,
            stream=_stream,
            response_type=ResponseType.MEDIA,
        )
        return _messages, _metadata

    # noinspection PyTypeChecker
    async def generate_patient_reply_image(
        self,
        *modifiers,
        simulation: Simulation | int = None,
        model: str = "gpt-image-1",
        stream: bool = False,
        output_format="webp",
        include_default=False,
        **kwargs,
    ) -> tuple[list[Message], list[SimulationMetadata]]:
        """
        Generate a patient image for a given simulation using OpenAI Image API.
        """
        func_name = inspect.currentframe().f_code.co_name
        logger.debug(f"[{func_name}] triggered...")

        # Get the simulation instance if provided as int
        simulation = await Simulation.aresolve(simulation)

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
        _input = build_patient_reply_payload()

        # Call OpenAI API Images API
        # See https://platform.openai.com/docs/api-reference/images
        try:
            response = await self.client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size="1024x1024",
                output_format=output_format,
                output_compression=70,
            )
        except Exception as e:
            logger.error(f"[{func_name}] OpenAI image generation failed: {e}")
            return e

        # Process Response and return a tuple with a list of Messages and Metadata
        _messages, _metadata = await process_response(
            response=response,
            simulation=simulation,
            stream=False,
            response_type=ResponseType.MEDIA,
            mime_type=mimetypes.guess_file_type(f"image.{output_format}")[0]
            or "image/webp",
        )
        return _messages, _metadata

    async def generate_patient_results(
        self,
        *modifiers,
        simulation: Simulation | int = None,
        lab_orders: str | list[str] = None,
        include_default=False,
        stream: bool = False,
        **kwargs,
    ) -> tuple[list[Message], list[SimulationMetadata]]:
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

        text: ResponseTextConfigParam = build_response_text_param(PatientResultsSchema)
        payload = await build_patient_results_payload(simulation, lab_orders)
        response = await self.client.responses.create(
            model=self.model,
            text=text,
            stream=stream,
            **payload,
        )

        # Process Response and return a tuple with a list of Messages and Metadata
        _messages, _metadata = await process_response(
            response,
            simulation,
            stream,
            response_type=ResponseType.PATIENT_RESULTS,
        )
        return _messages, _metadata
