import asyncio
import base64
import importlib
import inspect
import json
import logging
import mimetypes
import uuid
import warnings
from logging import DEBUG
from logging import WARNING
from typing import Coroutine
from typing import Optional

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from openai.types.responses.response_output_item import ImageGenerationCall
from twisted.python.compat import items

from chatlab.models import Message
from chatlab.models import RoleChoices
from core.utils import coerce_to_bool
from core.utils import remove_null_keys
from core.utils import to_pascal_case
from simcore.models import Simulation, RadResult, LabResult
from simcore.models import SimulationImage
from simcore.models import SimulationMetadata
from .models import Response
from .models import ResponseType
from .structured_output import PatientInitialSchema, PatientResultsSchema
from .structured_output import PatientReplySchema

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
            output: PatientInitialSchema | PatientReplySchema |
                    PatientResultsSchema | ImageGenerationCall | str,
            response_type: ResponseType = ResponseType.REPLY,
            **kwargs,
    ) -> tuple[list[Message], list[SimulationMetadata]]:
        """
        Parses the given output, instantiates it, and returns a tuple
        containing a list of created Message instances and a list
        of created SimulationMetadata instances.

        This method handles different types of output, including PatientInitialSchema,
        PatientReplySchema, ImageGenerationCall, and str by performing specific
        processing logic for each type. It also manages tasks associated with image
        generation for PatientReplySchema when required.

        Args:
            output: The output to be parsed; can be PatientInitialSchema,
              PatientReplySchema, ImageGenerationCall, or str.
            response_type (ResponseType): The type of response to handle,
              defaulting to ResponseType.REPLY.
            kwargs: Additional keyword arguments for custom behavior or configuration.

        Returns:
            tuple: A tuple containing two lists: one with Message objects and
             one with SimulationMetadata objects.
        """
        _created_messages = []
        match output:

            case PatientInitialSchema() | PatientReplySchema():

                # Build tasks by extracting each message text and metadata
                # NOTE: `build_schema_tasks` also automatically updates
                # `scenario_data` on the Simulation instance if provided
                message_tasks, metadata_tasks = await self.build_schema_tasks(output)

                # Concurrently run installation of Message and SimulationMetadata objects
                all_message_results, all_metadata_results = await asyncio.gather(
                    asyncio.gather(*message_tasks),
                    asyncio.gather(*metadata_tasks),
                )

                # Flatten Lists
                created_messages = [
                    msg for msgs in all_message_results for msg in msgs
                ]
                created_metadata = [
                    md for mds in all_metadata_results for md in mds
                ]

                if isinstance(output, PatientReplySchema):
                    # Check if an image was requested and trigger image generation
                    if image_requested := coerce_to_bool(output.image_requested):
                        # Lazy import to avoid circular dependency
                        from simai.tasks import generate_patient_reply_image_task as new_image_task

                        logger.debug(f"image_requested={image_requested}")
                        try:
                            new_image_task.delay(simulation_id=self.simulation.pk)
                        except Exception as e:
                            logger.warning(
                                f"[_parse_output] Celery image task failed to enqueue: {e}"
                            )

                return created_messages, created_metadata

            case ImageGenerationCall():

                # Create a new SimulationImage instance from the output, then
                # Create a new Message instance with the media attached and
                # Return it in a single-item list and an empty metadata list
                _image_instance = await self._parse_image_generation(output)
                _created_message = await self._parse_message(
                    message_string=None,
                    media=_image_instance
                )
                return [_created_message], []

            case PatientResultsSchema():

                _created_results: list[LabResult | RadResult] = await self._parse_results(output)
                return [], _created_results

            case str():

                # Create a new Message instance from the output and
                # Return it in a single-item list and an empty metadata list
                return [await self._parse_message(output)], []

            case _:

                raise ValueError(f"Unknown output type: {type(output)}")

    async def build_schema_tasks(
            self,
            schema: PatientInitialSchema | PatientReplySchema
    ) -> (list[Coroutine], list[Coroutine]):
        # Create new Message instances for each text string and
        # Add each to the `_created_messages` list
        _message_tasks: list[Coroutine] = []
        _metadata_tasks: list[Coroutine] = []

        # Stage Message creation tasks for each message in the schema
        _message_tasks.append(
            self._parse_messages(
                [m.content for m in schema.messages]
            )
        )

        # Dump Pydantic model to dict for metadata parsing
        metadata_dict: dict[str: str] = schema.metadata.model_dump()

        # Update the Simulation instance with scenario_data if provided
        # Then, remove the key so it isn't treated as metadata
        _scenario_data: dict[str: str] = metadata_dict.pop("scenario_data", {})
        await self._parse_scenario_attribute(_scenario_data)

        # Pop `patient_history` from dict for special parsing
        _patient_history = metadata_dict.pop("patient_history", {})
        # TODO: add `patient_history` tasks to `_metadata_tasks` here

        # Stage tasks to create each metafield, then
        # Create the metadata instances
        _metadata_tasks.extend([
            self._parse_metadata(
                entry,
                attribute=to_pascal_case(attribute),
            )
            for attribute, entries in metadata_dict.items()
            for entry in (entries if isinstance(entries, list) else [entries])
        ])

        return _message_tasks, _metadata_tasks

    async def parse_output_v1(
        self,
        output: dict or str,
        **kwargs,
    ) -> list[Message] | list[SimulationMetadata]:
        warnings.warn(
            message="`function is deprecated. Use `_parse_output` instead.",
            category=PendingDeprecationWarning,
            stacklevel=2
        )

        func_name = inspect.currentframe().f_code.co_name

        logger.debug(f"response output: {output}")

        if isinstance(output, str):
            output = json.loads(output)

        match self.response_type:

            case ResponseType.FEEDBACK:
                await self.log(func_name, f"Feedback Output: {output}")
                await self._parse_metadataV1(output, "SimulationFeedback")
                return []

            case ResponseType.PATIENT_RESULTS:
                _results = {
                    "LabResult": output.get("lab_results") or [],
                    "RadResult": output.get("radiology_results") or [],
                }

                results_tasks = []
                for attribute, data in _results.items():
                    logger.debug(f"[{func_name}] parsing {attribute} (data: {data})...")
                    if data:
                        results_tasks.append(
                            self._parse_metadata(
                                data,
                                attribute=attribute,
                                field_map={
                                    "order_name": "key",
                                    "result_value": "value",
                                },
                            )
                        )
                logger.debug(
                    f"[{func_name}] parsed {len(results_tasks)} results tasks..."
                )
                return [
                    item
                    for sublist in await asyncio.gather(*results_tasks)
                    for item in sublist
                ]

            case ResponseType.MEDIA:
                media_tasks = [
                    self._parse_media(
                        media_b64=media.b64_json, mime_type=kwargs.get("mime_type")
                    )
                    for media in output
                ]

                # Create SimulationImage objects (and ignore errors)
                media_list = await asyncio.gather(*media_tasks, return_exceptions=True)
                media_list = [m for m in media_list if not isinstance(m, Exception)]
                logger.debug(
                    f"[{func_name}] parsed {len(media_list)} media items... \n\nstarting content creation...\n"
                )

                # Create Message objects for each SimulationImage, then
                # return a list of messages
                message_tasks = [
                    self._parse_message(message_string=None, media=media)
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
                logger.warning(
                    f"[{func_name}] Celery image task failed to enqueue: {e}"
                )

        # If it's a full OpenAI response, merge all assistant content outputs
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
            merged_output = {
                "messages": [],
                "metadata": {"patient_metadata": {}, "simulation_metadata": []},
            }
            for chunk in output_chunks:
                merged_output["messages"].extend(chunk.get("messages") or [])
                metadata = chunk.get("metadata") or {}

                # Merge patient_metadata
                if "patient_metadata" in metadata:
                    merged_output["metadata"]["patient_metadata"].update(
                        metadata["patient_metadata"]
                    )

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
            k: v
            for k, v in patient_data.items()
            if k not in ("medical_history", "additional")
        }
        patient_metadata.update(patient_data.get("additional_metadata") or {})

        logger.debug(f"{func_name} parsed {len(messages)} messages")
        logger.debug(
            f"{func_name} simulation_data {type(simulation_data)}: {simulation_data}"
        )

        metadata_tasks = []
        if patient_metadata:
            metadata_tasks.append(
                self._parse_metadataV1(patient_metadata, "PatientDemographics")
            )
        if patient_history:
            metadata_tasks.append(
                self._parse_metadataV1(patient_history, "PatientHistory")
            )
        if simulation_data:
            metadata_tasks.append(
                self._parse_metadataV1(simulation_data, "SimulationMetadata")
            )
        if scenario_data:
            await self._parse_scenario_attribute(scenario_data)

        await asyncio.gather(*metadata_tasks)
        message_tasks = [self._parse_message(m) for m in messages]
        return await asyncio.gather(*message_tasks)

    async def _parse_message(self, message_string: str | None, **kwargs) -> Message:
        """
        Returns a single Message instance for the given text (or media).


        Args:
            message_string: The raw text content to wrap into a Message.
            media: Optional keyword arg; if provided, the media object.

        Returns:
            A newly created Message instance.
        """
        display_name = getattr(self.simulation, "sim_patient_display_name", "Unknown")
        content = message_string or None
        media = kwargs.get("media") or None

        # Build the payload to create a new Message instance, then
        payload = {
            "simulation": self.simulation,
            "sender": self.system_user,
            "display_name": display_name,
            "role": RoleChoices.ASSISTANT,
            "openai_id": self.response.id,
            "response": self.response,
            "content": content,
            "is_from_ai": True,
            "message_type": "image" if media is not None else None,
        }

        # Remove null values from the payload to avoid database errors, then,
        # Create the Message instance and add media if provided
        payload = remove_null_keys(payload)
        msg = await Message.objects.acreate(**payload)

        # Add media relation if media exists in kwargs
        if media is not None:
            from chatlab.utils import add_message_media
            await add_message_media(msg.id, media.id)

        return msg

    async def _parse_messages(
            self, message_strings: list[str]
    ) -> list[Message]:
        """
        Persist a Message for each text string provided, in parallel.

        Args:
            message_strings: List of raw text messages to parse and persist.

        Returns:
            A list of the created Message instances.
        """
        tasks = (
            self._parse_message(m) for m in message_strings
        )
        return list(await asyncio.gather(
            *(self._parse_message(m) for m in message_strings)
        ))

    async def _parse_text(self, content: dict | str | None, **kwargs) -> Optional[Message]:
        warnings.warn(
            message="`_parse_text` is deprecated. Use `_parse_message` instead.",
            category=PendingDeprecationWarning,
            stacklevel=2
        )

        func_name = inspect.currentframe().f_code.co_name
        await self.log(func_name, f"received input: {content or kwargs.get('media')}")

        display_name = getattr(self.simulation, "sim_patient_display_name", "Unknown")
        media = kwargs.get("media")

        # Try to convert to dict, otherwise assume it's a string'
        # If it's a string, convert it to a dict with the "content" key
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.debug(f"Unable to convert to dict. Assuming content is a string.")
            content = { "content": content }

        # Build the payload to create a new Message instance, then
        # Remove null values from the payload to avoid database errors, and
        # Create the Message instance and add media if provided
        payload = {
            "simulation": self.simulation,
            "sender": self.system_user,
            "display_name": display_name,
            "role": RoleChoices.ASSISTANT,
            "openai_id": self.response.id,
            "response": self.response,
            "content": content.get("content") if content else None,
            "is_from_ai": True,
            "message_type": "image" if media is not None else None,
        }
        payload = remove_null_keys(payload)
        msg = await Message.objects.acreate(**payload)

        # Add media relation if media exists
        if media is not None:
            from chatlab.utils import add_message_media

            await add_message_media(msg.id, media.id)

        return msg

    async def _parse_metadata(
        self,
        metadata: dict | list,
        attribute: str,
        field_map: dict[str, str] | None = None,
    ) -> SimulationMetadata | list[SimulationMetadata]:
        import importlib
        import inspect
        from django.db.models import Model

        func_name = inspect.currentframe().f_code.co_name
        logger.debug(
            f"[{func_name}] received {attribute} input ({type(metadata)}): {metadata}"
        )

        # List to store created instances
        instances = []

        # Dynamically import the model class based on the provided attribute
        try:
            module = importlib.import_module("simcore.models")
            Subclass: type[Model] = getattr(module, attribute)
        except (ModuleNotFoundError, AttributeError) as e:
            logger.error(f"[{func_name}] Invalid attribute '{attribute}': {e}")
            return []

        # Convert to list if necessary to handle single-entry metadata
        if not isinstance(metadata, list):
            metadata = [metadata]

        # Map field names to database model fields, if provided
        field_map = field_map or {}
        model_fields = {f.name for f in Subclass._meta.fields}

        # Iterate over metadata entries and create database objects
        for entry in metadata:
            if not isinstance(entry, dict):
                await self.log(func_name, f"Expected dict, got {type(entry)}", WARNING)
                continue

            # Prepare initialization kwargs for the new object,
            # then create the object and append it to `instances`
            try:
                init_kwargs = {"simulation": self.simulation}

                for input_key, value in entry.items():
                    model_key = field_map.get(input_key, input_key)
                    if model_key in model_fields:
                        init_kwargs[model_key] = value
                    else:
                        await self.log(
                            func_name,
                            f"Unrecognized key '{input_key}' not in field_map or model fields.",
                            WARNING,
                        )

                # Optional fallback for `value` field
                if "value" in model_fields and "value" not in init_kwargs:
                    fallback_keys = ["result_value", "diagnosis", "order_name"]
                    for fk in fallback_keys:
                        if fk in entry:
                            init_kwargs["value"] = str(entry[fk])
                            break
                    else:
                        init_kwargs["value"] = str(entry)

                # Create the object, then append it to `instances` and log it (DEBUG only)
                instance = await Subclass.objects.acreate(**init_kwargs)
                instances.append(instance)
                logger.debug(
                    f"new {attribute} created for Sim#{instance.simulation or "UNK"}: {instance.key or "UNK"}"
                )

            except Exception as e:
                await self.log(func_name, f"Error creating {attribute}: {e}", WARNING)

        return instances

    async def _parse_metadataV1(
        self, metadata: dict | list, attribute: str
    ) -> list[SimulationMetadata]:
        """
        Parses simulation metadata and creates corresponding database objects based on the
        provided attribute type. This function handles both dictionary and list types of
        metadata, determines the appropriate model class dynamically, and logs actions
        performed during metadata processing.

        :param metadata: Simulation metadata to be processed. Can be a dictionary or a list containing
                         metadata entries. Each entry within metadata should match the expected format
                         required to create a database object for the specific attribute.
        :type metadata: dict | list
        :param attribute: The name of the model class corresponding to the metadata being processed.
                          The function uses this attribute to dynamically find and import the class.
        :type attribute: str
        :return: A list of successfully created database objects corresponding to the given metadata.
        :rtype: list[SimulationMetadata]
        :raises ModuleNotFoundError: If the specified model module cannot be found.
        :raises AttributeError: If the specified attribute cannot be located in the module.
        """
        warnings.warn(
            message="`deprecated. Use `_parse_metadata` instead.",
            category=PendingDeprecationWarning,
            stacklevel=2
        )

        func_name = inspect.currentframe().f_code.co_name
        logger.debug(
            f"[{func_name}] received {attribute} input ({type(metadata)}): {metadata}"
        )

        instances = []

        try:
            module = importlib.import_module("simcore.models")
            Subclass = getattr(module, attribute)
        except (ModuleNotFoundError, AttributeError) as e:
            logger.error(f"[{func_name}] Invalid attribute '{attribute}': {e}")
            return []

        def clean_key(k: str) -> str:
            return k.lower().replace("_", " ").strip()

        async def create_field(**kwargs):
            obj = await Subclass.objects.acreate(**kwargs)
            instances.append(obj)
            await self.log(func_name, f"... new {attribute} created: {obj.key}", DEBUG)

        if attribute.casefold() == "patienthistory":
            for entry in metadata:
                if not isinstance(entry, dict):
                    await self.log(
                        func_name, f"Expected dict, got {type(entry)}", WARNING
                    )
                    continue
                await create_field(
                    simulation=self.simulation,
                    key=entry.get("diagnosis"),
                    is_resolved=entry.get("is_resolved"),
                    duration=entry.get("duration"),
                    value=f"{entry.get('diagnosis')} ({'resolved' if entry.get('is_resolved') else 'ongoing'})",
                )
            return instances

        if isinstance(metadata, dict):
            for key, value in metadata.items():
                value_str = (
                    json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                )
                await create_field(
                    simulation=self.simulation,
                    key=clean_key(key),
                    value=value_str,
                )
            return instances

        if isinstance(metadata, list):
            for index, item in enumerate(metadata):
                if isinstance(item, dict):
                    for key, value in item.items():
                        value_str = (
                            json.dumps(value)
                            if isinstance(value, (dict, list))
                            else str(value)
                        )
                        await create_field(
                            simulation=self.simulation,
                            key=f"Condition #{index} {clean_key(key)}",
                            value=value_str,
                        )
                else:
                    await self.log(
                        func_name,
                        f"Expected a dict in metadata list, but got {type(item)}",
                        WARNING,
                    )
            return instances

        await self.log(func_name, f"Unhandled metadata type: {type(metadata)}", WARNING)
        return []

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
                raise TypeError(
                    "Scenario attributes must be a dict or convertible to dict."
                )

        allowed_keys = {"diagnosis", "chief_complaint"}
        unknown_keys = set(attributes) - allowed_keys
        updated_fields = []

        if unknown_keys:
            raise ValueError(
                f"Unknown scenario attribute(s): {', '.join(unknown_keys)}"
            )

        for k, v in attributes.items():
            if k in allowed_keys:
                setattr(self.simulation, k, v)
                updated_fields.append(k)
            else:
                logger.warning(f"Ignored unknown scenario attribute: {k}={v}")

        if updated_fields:
            await sync_to_async(self.simulation.save)(update_fields=updated_fields)

    async def _parse_image_generation(self, output: ImageGenerationCall) -> SimulationImage:
        """
        Returns a single SimulationImage instance for the given image generation output.

        Args:
            output (ImageGenerationCall): An OpenAI ImageGenerationCall instance.

        Returns:
            The created SimulationImage instance.
        """
        func_name = inspect.currentframe().f_code.co_name

        _result = output.result
        _image_id = output.id
        _output_format = output.output_format
        _mime_type = mimetypes.guess_type(f"temp.{_output_format}")[0]


        # Try to decode the base64 image, then prepare the file in-memory
        try:
            image_bytes = base64.b64decode(_result)
            image_file = ContentFile(
                image_bytes, name=f"temp_{_image_id}.{_output_format}"
            )
        except Exception as e:
            raise Exception(f"[{func_name}] Failed to parse image generation call: {e}")

        # Build the payload to create a new SimulationImage object
        # Remove null values from the payload to avoid database errors, and
        # Create SimulationImage object
        payload = {
            "simulation": self.simulation,
            "openai_id": _image_id,
            "original": image_file,
            "mime_type": _mime_type,
        }
        payload = remove_null_keys(payload)
        image_instance = await SimulationImage.objects.acreate(**payload)

        return image_instance

    async def _parse_media(
        self, media_b64, mime_type, **kwargs
    ) -> SimulationImage | Exception:
        """
        Parse and create a Message object containing media content.

        Args:
            media_b64 (str): Base64-encoded media content (e.g., image).
            mime_type (str): MIME type (e.g., 'image/jpeg').
            **kwargs: Additional fields (ignored for now).

        Returns:
            SimulationImage: The created SimulationImage object.

        Raises:
            ValueError: If media content or mime_type is invalid

        """
        warnings.warn("Use `parse_image_generation` instead.", PendingDeprecationWarning, stacklevel=2)
        func_name = inspect.currentframe().f_code.co_name

        if not media_b64:
            raise ValueError("Media content is required, but was not provided.")

        if not mime_type:
            raise ValueError("MIME type is required, but was not provided.")

        # Prepare the image to save it to the database
        output_format = mimetypes.guess_extension(mime_type) or ".webp"
        try:
            # Decode base64 image, then prepare the file in-memory
            image_bytes = base64.b64decode(media_b64)
            image_uuid = uuid.uuid4()
            image_file = ContentFile(
                image_bytes, name=f"temp_{image_uuid}.{output_format}"
            )

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
        image_instance = await sync_to_async(SimulationImage.objects.create)(**payload)

        return image_instance

    async def _parse_results(
            self,
            results: PatientResultsSchema
    ) -> list[LabResult | RadResult]:
        """
        Persist a LabResult or RadResult for each text string provided, in parallel.

        Args:
            results (list[LabResult | RadResult): List of LabResult or
              RadResult objects to parse and persist.

        Returns:
            list[LabResult | RadResult]: List of the created LabResult or
              RadResult instances.
        """
        _tasks: list[Coroutine] = []

        # Stage Lab Result(s) task(s)
        _tasks.extend(
            [
                self._parse_metadata(
                    metadata=lr.model_dump(),
                    attribute="LabResult",
                    field_map={
                        "result_value": "value",
                        "diagnosis": "diagnosis",
                        "order_name": "order_name",
                    },
                )
                for lr in results.lab_results or []
            ]
        )

        # Stage Radiology Result(s) task(s)
        _tasks.extend(
            [
                self._parse_metadata(
                    metadata=rr.model_dump(),
                    attribute="RadResult",
                    field_map={
                        "result_value": "value",
                        "order_name": "key",
                    },
                )
                for rr in results.radiology_results or []
            ]
        )

        # Create instances concurrently via `_parse_metadata`, then
        # flatten the results and return the list of instances
        raw_lists = await asyncio.gather(*_tasks)
        return [item for sublist in raw_lists for item in sublist]

    @staticmethod
    async def log(func_name, msg="triggered", level=DEBUG) -> None:
        return logger.log(level, f"[{func_name}]: {msg}")
