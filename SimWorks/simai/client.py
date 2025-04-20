import logging
from typing import List
from typing import Optional

from chatlab.models import Message
from chatlab.models import Simulation
from simai.parser import OpenAIResponseParser
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIChatService:
    def __init__(self, model: Optional[str] = None):
        self.model = model or getattr(settings, "OPENAI_MODEL", "gpt-4")
        self.client = OpenAI()

    def get_response(self, user_msg: Message) -> List[Message]:
        logger.info(
            f"Requesting SimMessage for Simulation #{user_msg.simulation.pk} "
            f"in response to {user_msg.sender}'s input (ID: {user_msg.id})..."
        )

        response = self.client.responses.create(
            model=self.model,
            previous_response_id=user_msg.get_previous_openai_id(),
            input=user_msg.get_openai_input(),
        )

        user_msg.set_openai_id(response.id)

        parser = OpenAIResponseParser(user_msg.simulation)
        return parser.parse_full_response(response.output_text, response.id)

    def get_initial_response(self, simulation: Simulation) -> List[Message]:
        if not simulation.prompt:
            from chatlab.models import get_default_prompt

            simulation.prompt_id = get_default_prompt()
            simulation.save()

        instruction = simulation.prompt.text.strip()
        instruction += (
            f"\n\nYour name is {simulation.sim_patient_full_name}. "
            f"Stay in character as {simulation.sim_patient_full_name} and respond accordingly."
        )

        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "developer", "content": instruction},
                {"role": "user", "content": "Begin simulation"},
            ],
        )

        logger.debug(
            f"Generated initial scenario message for Simulation {simulation.id}"
        )
        logger.info(
            f"[SIM #{simulation.id}] OpenAI Initial response: {response.output_text}"
        )

        parser = OpenAIResponseParser(simulation)
        return parser.parse_full_response(response.output_text, response.id)
