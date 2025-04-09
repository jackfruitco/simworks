import json
import logging
from typing import List, Optional, Tuple

from asgiref.sync import sync_to_async

from ChatLab.models import Message, Simulation, RoleChoices
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()

def _get_system_user():
    """
    Lazy-loads the system user.
    """
    user, _ = User.objects.get_or_create(
        username="System", defaults={"first_name": "System", "is_active": False}
    )
    return user


class OpenAIResponseParser:
    """
    A utility class responsible for parsing OpenAI response output into metadata and messages.
    """

    def __init__(self, simulation: Simulation, system_user):
        self.simulation = simulation
        self.system_user = system_user

    async def parse_full_response(
        self, output_text: str, openai_id: Optional[str] = None
    ) -> List[Message]:
        """
        Parses a full OpenAI response into metadata and assistant messages.
        """
        metadata_str, content = self._split_output(output_text)
        await self._parse_metadata(metadata_str)
        return await self._parse_messages(content, openai_id)

    def _split_output(self, output_text: str) -> Tuple[str, str]:
        """
        Splits the OpenAI response into metadata and content.
        """
        output = output_text.strip()
        if not output:
            return "{}", ""
        if ";" in output:
            return output.split(";", 1)
        if output.startswith("{") and output.endswith("}"):
            return output, ""
        return "{}", output

    async def _parse_metadata(self, metadata_str: str) -> None:
        """
        Parses and saves metadata from the OpenAI response.
        """
        try:
            data = json.loads(metadata_str.replace("'", '"'))
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenAI metadata JSON: %s", e)
            data = {}

        for key, value in data.items():
             await sync_to_async(self.simulation.metadata.create)(
                 key=key.lower(),
                 value=str(value).lower()
            )

    async def _parse_messages(self, content: str, openai_id: Optional[str] = None) -> List[Message]:
        display_name = getattr(self.simulation, "sim_patient_display_name", "Unknown")
        message_texts = [msg.strip() for msg in content.split("SimMsg:")[1:] if msg.strip()]
        messages = []

        for msg_text in message_texts:
            msg = await sync_to_async(Message.objects.create)(
                simulation=self.simulation,
                sender=self.system_user,
                display_name=display_name,
                role=RoleChoices.ASSISTANT,
                content=msg_text,
                openai_id=openai_id,
            )
            messages.append(msg)

        return messages
