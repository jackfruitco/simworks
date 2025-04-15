import asyncio
import inspect
import json
import logging
from logging import DEBUG
from logging import WARNING
from typing import List
from typing import Optional
from typing import Tuple

from asgiref.sync import sync_to_async
from ChatLab.models import Message
from ChatLab.models import RoleChoices
from ChatLab.models import Simulation
from ChatLab.models import SimulationMetadata
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


class StructuredOutputParser:
    """
    A utility class responsible for parsing the OpenAI structured output into metadata and messages...
    """

    def __init__(self, simulation: Simulation, system_user: User, response):
        self.simulation = simulation
        self.system_user = system_user
        self.response = response

    async def parse_output(self, output: dict or str) -> List[Message]:
        """
        Parses the OpenAI structured output, saving metadata as SimulationMetadata objects and
        returning a list of messages.
        """
        func_name = inspect.currentframe().f_code.co_name

        # Convert output to dict if provided as string
        if type(output) is str:
            output = json.loads(output)

        messages = output.get("messages", [])
        metadata = output.get("metadata", {})

        # For patient metadata, we assume 'patient' is a dictionary that can contain both
        # general metadata (demographics, etc.) and a separate "history" key.
        patient_data = metadata.get("patient_metadata", {})
        simulation_data = metadata.get("simulation_metadata", {})

        # Separate medical_history metadata from patient_metadata:
        patient_history = patient_data.get("medical_history", {})

        # Pull additional metadata into top-level patient_metadata
        patient_metadata = {
            k: v
            for k, v in patient_data.items()
            if k not in ("medical_history", "additional")
        }
        patient_metadata.update(patient_data.get("additional_metadata", {}))

        logger.debug(
            f"{func_name} parsed {len(messages)} {'message' if len(messages) == 1 else 'messages'}:"
        )
        logger.debug(
            f"{func_name} simulation_data {type(simulation_data)}: {simulation_data}"
        )

        # Create tasks for saving metadata concurrently.
        metadata_tasks = []
        if patient_metadata:
            metadata_tasks.append(
                self._parse_metadata(patient_metadata, "patient metadata")
            )
        if patient_history:
            metadata_tasks.append(
                self._parse_metadata(patient_history, "patient history")
            )
        if simulation_data:
            metadata_tasks.append(
                self._parse_metadata(simulation_data, "simulation metadata")
            )

        await asyncio.gather(*metadata_tasks)

        # Process messages concurrently
        message_tasks = [self._parse_message(message) for message in messages]
        await self.log(func_name, f"message_tasks built: {message_tasks}")
        return await asyncio.gather(*message_tasks)

    async def _parse_message(self, message: dict) -> Optional[Message]:
        func_name = inspect.currentframe().f_code.co_name
        await self.log(func_name, f"received input: {message}")

        display_name = getattr(self.simulation, "sim_patient_display_name", "Unknown")

        return await sync_to_async(Message.objects.create)(
            simulation=self.simulation,
            content=message["content"],
            sender=self.system_user,
            display_name=display_name,
            role=RoleChoices.ASSISTANT,
            openai_id=self.response.id,
            response=self.response,
        )

    async def _parse_metadata(self, metadata: dict, attribute: str) -> None:
        """
        Processes a metadata structure and creates SimulationMetadata objects.

        If metadata is a dict, it iterates over its key/value pairs.
        If it is a list, it iterates over each element (which should be dicts) and
        then over each key/value pair inside them.

        :param metadata: A dict or list containing the metadata.
        :param attribute: A string describing the type of metadata (e.g., "patient history").
        """
        func_name = inspect.currentframe().f_code.co_name
        logger.debug(f"[{func_name}] received input ({type(metadata)}): {metadata}")

        if isinstance(metadata, dict):
            # Process key-value pairs from the dict
            for key, value in metadata.items():
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value)
                else:
                    value_str = str(value)
                metafield = await sync_to_async(SimulationMetadata.objects.create)(
                    simulation=self.simulation,
                    key=key.lower(),
                    value=value_str,
                    attribute=attribute,
                )
                await self.log(
                    func_name, f"... new metafield created: {metafield.key}", DEBUG
                )
        elif isinstance(metadata, list):
            # Process each dictionary in the list
            for index, item in enumerate(metadata):
                if isinstance(item, dict):
                    for key, value in item.items():
                        if isinstance(value, (dict, list)):
                            value_str = json.dumps(value)
                        else:
                            value_str = str(value)
                        # Append index to key for uniqueness if needed
                        metafield = await sync_to_async(
                            SimulationMetadata.objects.create
                        )(
                            simulation=self.simulation,
                            key=f"Condition #{index} {key.lower()}",
                            value=value_str,
                            attribute=attribute,
                        )
                        await self.log(
                            func_name,
                            f"... new metafield created: {metafield.key}",
                            DEBUG,
                        )
                else:
                    await self.log(
                        func_name,
                        f"Expected a dict in metadata list, but got {type(item)}",
                        WARNING,
                    )
        else:
            logger.warning(
                func_name,
                f"Expected metadata to be a dict or list, but got {type(metadata)}",
                WARNING,
            )

    @staticmethod
    async def log(func_name, msg="triggered", level=DEBUG) -> None:
        return logger.log(level, f"[{func_name}]: {msg}")


class OpenAIResponseParser:
    """
    A utility class responsible for parsing OpenAI response output into metadata and messages.
    """

    def __init__(self, simulation: Simulation, system_user):
        self.simulation = simulation
        self.system_user = system_user
        logger.error(
            "[DEPRECATED] `OpenAIResponseParser` is deprecated. Please use `StructuredOutputParser` instead."
        )

    async def parse_full_response(
        self, output_text: str, openai_id: Optional[str] = None
    ) -> List[Message]:
        """
        Parses a full OpenAI response into metadata and assistant messages.
        """
        metadata_str, content = self._split_output(output_text)
        await self._parse_metadata(metadata_str)
        return await self._parse_messages(content, openai_id)

    @staticmethod
    async def _split_output(output_text: str) -> Tuple[str, str]:
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
                key=key.lower(), value=str(value).lower()
            )

    async def _parse_messages(
        self, content: str, openai_id: Optional[str] = None
    ) -> List[Message]:
        display_name = getattr(self.simulation, "sim_patient_display_name", "Unknown")
        message_texts = [
            msg.strip() for msg in content.split("SimMsg:")[1:] if msg.strip()
        ]
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
