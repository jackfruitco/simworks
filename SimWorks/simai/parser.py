import asyncio
import base64
import inspect
import json
import logging
import mimetypes
import uuid
from logging import DEBUG
from logging import WARNING
from typing import List
from typing import Optional
from typing import Tuple

from channels.db import database_sync_to_async
from django.core.files.base import ContentFile
from django.db.models import QuerySet

from core.utils import remove_null_keys
from core.utils.system import coerce_to_bool
from .models import ResponseType, Response
from asgiref.sync import sync_to_async
from chatlab.models import Message
from chatlab.models import RoleChoices
from simcore.models import Simulation, SimulationMetadata, SimulationImage
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


class StructuredOutputParser:
    """
    A utility class responsible for parsing the OpenAI structured output into metadata and messages...
    """

    def __init__(
            self,
            simulation: Simulation,
            response: Response,
            system_user: User,
            response_type: ResponseType = ResponseType.REPLY,
    ):
        self.simulation = simulation
        self.response = response
        self.system_user = system_user
        self.response_type = response_type

    async def parse_output(
            self,
            output: dict or str,
            **kwargs,
    ) -> List[Message]:
        func_name = inspect.currentframe().f_code.co_name

        logger.debug(f"response output: {output}")

        if isinstance(output, str):
            output = json.loads(output)

        if self.response_type is ResponseType.FEEDBACK:
            await self.log(func_name, f"Feedback Output: {output}")
            await self._parse_metadata(output, "SimulationFeedback")
            return []
        if self.response_type is ResponseType.PATIENT_RESULTS:
            results = output.get("patient_results") or []
            results_tasks = []
            for result in results:
                results_tasks.append(self._parse_metadata(result, "patient results"))
            await asyncio.gather(*results_tasks)

        # If it's a media response, parse each media item and return the results
        if self.response_type is ResponseType.MEDIA:
            media_tasks = [
                self._parse_media(
                    media_b64=media.b64_json,
                    mime_type=kwargs.get("mime_type")
                )
                for media in output
            ]
            # Create SimulationImage objects (and ignore errors)
            media_list = await asyncio.gather(*media_tasks, return_exceptions=True)
            media_list = [m for m in media_list if not isinstance(m, Exception)]
            logger.debug(f"[{func_name}] parsed {len(media_list)} media items... \n\nstarting message creation...\n")

            # Create Message objects for each SimulationImage, then
            # return a list of messages
            message_tasks = [
                self._parse_message(
                    message=None,
                    media=media
                )
                for media in media_list
            ]
            return await asyncio.gather(*message_tasks)

        # Check if an image was requested and trigger image generation
        if image_requested := coerce_to_bool(output.get("image_requested", False)):
            # Lazy import to avoid circular dependency
            from simai.tasks import generate_patient_reply_image_task as new_image_task
            logger.debug(f"[{func_name}]: image_requested={image_requested}")
            try:
                new_image_task.delay(simulation_id=self.simulation.pk)
            except Exception as e:
                logger.warning(f"[{func_name}] Celery image task failed to enqueue: {e}")

        # If it's a full OpenAI response, merge all assistant message outputs
        if isinstance(output, dict) and "output" in output:
            assistant_messages = output["output"]
            output_chunks = []

            for msg in assistant_messages:
                for part in msg.get("content") or []:
                    if part.get("type") == "output_text":
                        try:
                            parsed = json.loads(part["content"])
                            output_chunks.append(parsed)
                        except json.JSONDecodeError as e:
                            logger.warning(f"[{func_name}] Failed to parse part: {e}")

            # Merge messages and metadata
            merged_output = {"messages": [], "metadata": {"patient_metadata": {}, "simulation_metadata": []}}
            for chunk in output_chunks:
                merged_output["messages"].extend(chunk.get("messages") or [])
                metadata = chunk.get("metadata") or {}

                # Merge patient_metadata
                if "patient_metadata" in metadata:
                    merged_output["metadata"]["patient_metadata"].update(metadata["patient_metadata"])

                # Extend simulation_metadata list
                if "simulation_metadata" in metadata:
                    merged_output["metadata"]["simulation_metadata"].extend(
                        metadata["simulation_metadata"]
                    )

            output = merged_output

        # Now handle the normal parsing flow
        messages = output.get("messages") or []
        metadata = output.get("metadata") or {}

        # Gracefully handle missing or null metadata blocks
        patient_data = metadata.get("patient_metadata") or {}
        simulation_data = metadata.get("simulation_metadata") or {}
        scenario_data = metadata.get("scenario_metadata") or {}
        patient_history = patient_data.get("medical_history") or {}
        patient_metadata = {
            k: v for k, v in patient_data.items() if k not in ("medical_history", "additional")
        }
        patient_metadata.update(patient_data.get("additional_metadata") or {})

        logger.debug(f"{func_name} parsed {len(messages)} messages")
        logger.debug(f"{func_name} simulation_data {type(simulation_data)}: {simulation_data}")

        metadata_tasks = []
        if patient_metadata:
            metadata_tasks.append(self._parse_metadata(patient_metadata, "PatientDemographics"))
        if patient_history:
            metadata_tasks.append(self._parse_metadata(patient_history, "PatientHistory"))
        if simulation_data:
            metadata_tasks.append(self._parse_metadata(simulation_data, "SimulationMetadata"))
        if scenario_data:
            await self._parse_scenario_attribute(scenario_data)

        await asyncio.gather(*metadata_tasks)
        message_tasks = [self._parse_message(m) for m in messages]
        return await asyncio.gather(*message_tasks)

    async def _parse_message(self, message: dict | None, **kwargs) -> Optional[Message]:
        func_name = inspect.currentframe().f_code.co_name
        await self.log(func_name, f"received input: {message or kwargs.get('media')}")

        display_name = getattr(self.simulation, "sim_patient_display_name", "Unknown")
        media = kwargs.get("media")

        # Build the payload to create a new Message instance, then
        # Remove null values from payload to avoid database errors, and
        # Create the Message instance and add media if provided
        payload = {
            "simulation": self.simulation,
            "sender": self.system_user,
            "display_name": display_name,
            "role": RoleChoices.ASSISTANT,
            "openai_id": self.response.id,
            "response": self.response,
            "content": message.get("content") if message else None,
            "is_from_ai": True,
            "message_type": "image" if media is not None else None
        }
        payload = remove_null_keys(payload)
        msg = await sync_to_async(Message.objects.create)(**payload)

        # Add media relation if media exists
        if media is not None:
            from chatlab.utils import add_message_media
            await add_message_media(msg.id, media.id)

        return msg

    async def _parse_metadata(self, metadata: dict | list, attribute: str) -> None:
        import importlib
        func_name = inspect.currentframe().f_code.co_name
        logger.debug(f"[{func_name}] received {attribute} input ({type(metadata)}): {metadata}")

        try:
            module = importlib.import_module("simcore.models")
            Subclass = getattr(module, attribute)
        except (ModuleNotFoundError, AttributeError) as e:
            logger.error(f"[{func_name}] Invalid attribute '{attribute}': {e}")
            return

        if attribute.casefold() == "patienthistory":
            for entry in metadata:
                if not isinstance(entry, dict):
                    await self.log(func_name, f"Expected dict, got {type(entry)}", WARNING)
                    continue
                metafield = await sync_to_async(Subclass.objects.create)(
                    simulation=self.simulation,
                    key=entry.get("diagnosis"),
                    is_resolved=entry.get("is_resolved"),
                    duration=entry.get("duration"),
                    value=f"{entry.get('diagnosis')} ({'resolved' if entry.get('is_resolved') else 'ongoing'})"
                )
                await self.log(func_name, f"... new {attribute} created: {metafield.key}", DEBUG)
            return

        if isinstance(metadata, dict):
            for key, value in metadata.items():
                value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                metafield = await sync_to_async(Subclass.objects.create)(
                    simulation=self.simulation,
                    key=key.lower().replace("_", " "),
                    value=value_str,
                )
                await self.log(func_name, f"... new {attribute} created: {metafield.key}", DEBUG)
            return

        if isinstance(metadata, list):
            for index, item in enumerate(metadata):
                if isinstance(item, dict):
                    for key, value in item.items():
                        value_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                        metafield = await sync_to_async(Subclass.objects.create)(
                            simulation=self.simulation,
                            key=f"Condition #{index} {key.lower().replace('_', ' ')}",
                            value=value_str,
                        )
                        await self.log(func_name, f"... new {attribute} created: {metafield.key}", DEBUG)
                else:
                    await self.log(func_name, f"Expected a dict in metadata list, but got {type(item)}", WARNING)
            return

        logger.warning(f"[{func_name}] Expected metadata to be a dict or list, but got {type(metadata)}")

    async def _parse_scenario_attribute(self, attributes: dict) -> None:
        """
        Validates and applies scenario attributes to this simulation.
        Accepts a dict with optional 'diagnosis' and 'chief_complaint' keys.

        Raises:
            TypeError: if input is not a dict-like object.
            ValueError: if an unknown key is encountered.
        """
        if not isinstance(attributes, dict):
            try:
                attributes = dict(attributes)
            except Exception:
                raise TypeError("Scenario attributes must be a dict or convertible to dict.")

        allowed_keys = {"diagnosis", "chief_complaint"}
        unknown_keys = set(attributes) - allowed_keys
        updated_fields = []

        if unknown_keys:
            raise ValueError(f"Unknown scenario attribute(s): {', '.join(unknown_keys)}")

        for k, v in attributes.items():
            if k in allowed_keys:
                setattr(self.simulation, k, v)
                updated_fields.append(k)
            else:
                logger.warning(f"Ignored unknown scenario attribute: {k}={v}")

        if updated_fields:
            await sync_to_async(self.simulation.save)(update_fields=updated_fields)
            
    async def _parse_media(self, media_b64, mime_type, **kwargs) -> SimulationImage | Exception:
        """
        Parse and create a Message object containing media content.
    
        Args:
            media_b64 (str): Base64-encoded media content (e.g., image).
            mime_type (str): MIME type (e.g., 'image/jpeg').
            **kwargs: Additional fields (ignored for now).
    
        Returns:
            TODO Message: A new Message instance containing the parsed media content
    
        Raises:
            ValueError: If media content or mime_type is invalid

        """
        func_name = inspect.currentframe().f_code.co_name

        if not media_b64:
            raise ValueError("Media content is required, but was not provided.")

        if not mime_type:
            raise ValueError("MIME type is required, but was not provided.")

        # Prepare image to save to database
        output_format = mimetypes.guess_extension(mime_type) or ".webp"
        try:
            # Decode base64 image, then prepare file in-memory
            image_bytes = base64.b64decode(media_b64)
            image_uuid = uuid.uuid4()
            image_file = ContentFile(image_bytes, name=f"temp_{image_uuid}.{output_format}")

        except Exception as e:
            logger.error(f"[{func_name}] Failed to parse media: {e}")
            return e

        # Build the payload to create a new SimulationImage object
        # Remove null values from the payload to avoid database errors, and
        # Create SimulationImage object
        payload = {
            "simulation": self.simulation,
            "uuid": image_uuid,
            "original": image_file,
            "mime_type": mime_type,
        }
        payload = remove_null_keys(payload)
        image_instance = await sync_to_async(SimulationImage.objects.create)(
            **payload
        )

        return image_instance

    @staticmethod
    async def log(func_name, msg="triggered", level=DEBUG) -> None:
        return logger.log(level, f"[{func_name}]: {msg}")
    