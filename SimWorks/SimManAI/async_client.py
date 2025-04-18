"""
This module provides an asynchronous client for interacting with the OpenAI API
to facilitate patient simulations in a chat environment. It includes functions
to build payloads for patient replies and introductions, and a service class
to generate responses using the OpenAI model.
"""

import inspect
import logging
from typing import List
from typing import Optional

from asgiref.sync import sync_to_async
from ChatLab.models import Message
from ChatLab.models import Simulation
from . import prompts
from .output_schemas import build_message_schema
from .openai_gateway import process_response
from django.conf import settings
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

@sync_to_async
def build_patient_intro_payload(simulation: Simulation, prompt) -> List[dict]:
    """
    Build the initial payload for the patient's introduction in the simulation.

    Args:
        simulation (Simulation): The simulation object containing prompt and patient information.
        prompt (Prompt): The prompt object containing prompt information for this simulation.

    Returns:
        List[dict]: A list of dictionaries representing the role and content for the introduction.
    """
    instruction = prompt.content.strip()
    instruction += (
        f"\n\nYour name is {simulation.sim_patient_full_name}. "
        f"Stay in character as {simulation.sim_patient_full_name} and respond accordingly."
    )
    return [
        {"role": "developer", "content": instruction},
        {"role": "user", "content": "Begin simulation"},
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
        "previous_response_id": user_msg.get_previous_openai_id(),
        "input": user_msg.get_openai_input(),
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
    last_ai_msg = (
        simulation.message_set.filter(openai_id__isnull=False)
        .order_by("-timestamp")
        .first()
    )
    return {
        "previous_response_id": last_ai_msg.openai_id if last_ai_msg else None,
        "input": [
            {"role": "developer", "content": prompts.Feedback.default()},
            {"role": "user", "content": "Provide feedback to the user"},
        ],
    }


class AsyncOpenAIChatService:
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

    @staticmethod
    async def log(func_name, msg="triggered", level=logging.DEBUG) -> None:
        return logger.log(level, f"[{func_name}]: {msg}")

    async def generate_patient_intro(
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

        prompt = await sync_to_async(simulation.get_or_assign_prompt)()
        text = await build_message_schema(initial=True)

        input_payload = await build_patient_intro_payload(
            simulation, prompt
        )  # Build the payload for the introduction
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

        # Build payload (prompt, instructions), then get response from OpenAI
        payload = await build_patient_reply_payload(user_msg)
        text = await build_message_schema()
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
        response = await self.client.responses.create(
            model=self.model,
            stream=stream,
            **payload,
        )

        return await process_response(response, simulation, stream, response_type='feedback')
