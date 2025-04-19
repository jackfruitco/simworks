import asyncio
import inspect
import json
import logging
from logging import DEBUG
from logging import WARNING
from typing import List
from typing import Optional
from typing import Tuple

from .models import ResponseType
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

    async def parse_output(self, output: dict or str, response_type: ResponseType=ResponseType.REPLY) -> List[Message]:
        """
        Parses the OpenAI structured output, saving metadata as SimulationMetadata objects and
        returning a list of messages.
        """
        func_name = inspect.currentframe().f_code.co_name

        # Convert output to dict if provided as string
        if type(output) is str:
            output = json.loads(output)

        if response_type is ResponseType.FEEDBACK:
            await self.log(func_name, f"Feedback Output: {output}" )
            # feedback = output.get("metadata", {})
            await self._parse_metadata(output, response_type.label)
            return []

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
                    key=key.lower().replace("_", " "),
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
                            key=f"Condition #{index} {key.lower().replace("_", " ")}",
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