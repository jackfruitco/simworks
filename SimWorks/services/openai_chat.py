import json
import logging
from typing import List
from typing import Optional
from typing import Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from ChatLab.models import Message
from ChatLab.models import RoleChoices
from ChatLab.models import Simulation
from ChatLab.models import SimulationMetafield
from openai import OpenAI

"""
This module contains functionality to interact with the OpenAI API
to generate AI responses based on user messages within a simulation context.
It also parses the API responses to create Message and SimulationMetadata objects.
"""

logger = logging.getLogger(__name__)

# Instantiate the OpenAI client
client = OpenAI()

User = get_user_model()
# Retrieve or create the system user for AI responses.
system_user, _ = User.objects.get_or_create(
    username="System", defaults={"first_name": "System", "is_active": False}
)


def get_response(
    user_msg: Message, model: Optional[str] = None
) -> QuerySet[Message, Message]:
    """
    Generates an AI response for a given user message and creates corresponding metadata and chat Message records.

    This function sends the user's input to OpenAI, expects the response to contain either:
      - Both a metadata section and a chat content section separated by a semicolon,
      - Or a response that is only metadata (valid JSON),
      - Or only chat content.
    It then parses and creates:
      - SimulationMetafield objects using parse_response_metadata.
      - Chat Message objects using parse_response_content.

    :param user_msg: A Message object containing the user's input.
    :param model: Optional OpenAI model to use; defaults to the model specified in settings (typically "gpt-4").
    :return: A QuerySet of newly created Message objects representing the AI-generated chat responses.
    """
    if model is None:
        model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")

    logger.info(
        f"Requesting SimMessage for Simulation #{user_msg.simulation.pk} in response to {user_msg.sender}'s input (ID: {user_msg.id})..."
    )

    response = client.responses.create(
        model=model,
        previous_response_id=user_msg.get_previous_openai_id(),
        input=user_msg.get_openai_input(),
    )

    # Record the OpenAI response ID on the user's message for context.
    user_msg.set_openai_id(response.id)

    # Use the helper to split the response into metadata and chat content.
    data_str, content = split_openai_response(response.output_text)

    # Create metadata records (if any).
    parse_response_metadata(data_str=data_str, simulation=user_msg.simulation)

    # Create and return chat message records.
    messages = parse_response_content(
        content=content, simulation=user_msg.simulation, openai_id=response.id
    )

    return messages


def get_initial_response(
    simulation: Simulation, model: Optional[str] = None
) -> QuerySet[Message]:
    """
    Generates the initial scenario introduction for a simulation via an AI-generated response.

    This function constructs a prompt based on the simulation’s details,
    sends it to OpenAI, parses the returned response to extract both metadata
    and chat messages, and creates the appropriate database records.

    :param simulation: A Simulation instance.
    :param model: Optional OpenAI model to use; defaults to the model specified in settings.
    :return: A QuerySet of Message objects representing the initial chat messages.
    """
    if model is None:
        model = getattr(settings, "OPENAI_MODEL", "gpt-4")

    # Ensure the simulation has a prompt; if not, use a default prompt.
    if not simulation.prompt:
        from ChatLab.models import get_default_prompt  # Assumes this function exists.

        simulation.prompt_id = get_default_prompt()
        simulation.save()

    prompt = simulation.prompt.content.strip()
    prompt += f"\n\nYour name is {simulation.sim_patient_full_name}. Stay in character as {simulation.sim_patient_full_name} and respond accordingly."

    response = client.responses.create(
        model=model,
        instructions=prompt,
        input='Begin Simulation.',
    )

    logger.debug(f"Generated initial scenario message for Simulation {simulation.id}")
    logger.debug(f"Response: {response.output_text}")

    data_str, content = split_openai_response(response.output_text)
    logger.info(
        f"[SIM #{simulation.id}] OpenAI Initial response: {response.output_text}"
    )

    parse_response_metadata(data_str=data_str, simulation=simulation)
    messages = parse_response_content(
        content=content, simulation=simulation, openai_id=response.id
    )
    return messages


def split_openai_response(output_text: str) -> Tuple[str, str]:
    """
    Splits the OpenAI response output_text into two parts:
      - data_str: expected to be a JSON-like string containing metadata,
      - content: the chat message content, delimited by 'SimMsg:' if present.

    The logic is:
      1. If the output is empty, return ("{}", "").
      2. If a semicolon (;) is present, split on the first semicolon.
      3. Otherwise, if the output starts with '{' and ends with '}', treat it as pure JSON.
      4. Otherwise, treat the entire output as chat content with no metadata.

    :param output_text: The raw output text from OpenAI.
    :return: A tuple (data_str, content).
    """
    output = output_text.strip()
    if not output:
        return "{}", ""
    if ";" in output:
        data_str, content = output.split(";", 1)
        return data_str, content
    else:
        # If it's a JSON string, assume it's metadata only.
        if output.startswith("{") and output.endswith("}"):
            return output, ""
        else:
            # Otherwise, assume it's only chat content.
            return "{}", output


def parse_response_metadata(
    data_str: str, simulation: Simulation
) -> QuerySet[SimulationMetafield]:
    """
    Parses a JSON-like string containing metadata from an OpenAI response and creates SimulationMetafield objects.

    :param data_str: Data string to parse (expected to be JSON with keys and values, possibly using single quotes).
    :param simulation: A Simulation instance.
    :return: A QuerySet of newly created SimulationMetafield objects.
    """
    created_pks = []
    try:
        data = json.loads(data_str.replace("'", '"'))
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON: %s", e)
        data = {}

    for key, value in data.items():
        metafield = simulation.metadata.create(
            key=key.lower(), value=str(value).lower()
        )
        created_pks.append(metafield.pk)
    return simulation.metadata.filter(pk__in=created_pks)


def parse_response_content(
    content: str, simulation: Simulation, openai_id: Optional[str] = None
) -> QuerySet[Message]:
    """
    Parses the chat content from an OpenAI response and creates Message objects.

    The content is expected to be a string where individual messages are separated by "SimMsg:".
    Leading and trailing whitespace is trimmed from each message.

    :param content: The response content string containing chat messages.
    :param simulation: A Simulation instance.
    :param openai_id: Optional OpenAI response ID for tracking purposes.
    :return: A QuerySet of newly created Message objects.
    """
    display_name = getattr(simulation, "sim_patient_display_name", "Unknown")
    message_texts: List[str] = [msg.strip() for msg in content.split("SimMsg:")[1:]]
    created_pks = []
    for msg_text in message_texts:
        sim_msg = Message.objects.create(
            simulation=simulation,
            sender=system_user,
            display_name=display_name,
            role=RoleChoices.ASSISTANT,
            content=msg_text,
            openai_id=openai_id,
        )
        created_pks.append(sim_msg.pk)
    return Message.objects.filter(pk__in=created_pks)
