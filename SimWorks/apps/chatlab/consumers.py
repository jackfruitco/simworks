from datetime import UTC, datetime
from enum import StrEnum
import inspect
import json
import logging
import uuid

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import reverse
from django.utils import timezone

from apps.simcore.models import Simulation
from apps.simcore.utils import get_user_initials
from orchestrai.utils.json import json_default

from .models import Message

logger = logging.getLogger(__name__)

SYSTEM_USER = "system@medsim.local"


class ContentMode(StrEnum):
    HTML = "fullHtml"
    RAW = "rawOutput"
    TRIGGER = "trigger"


class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.simulation_id = None
        self.room_name = None
        self.room_group_name = None
        self.simulation = None

        self.content_mode = None

    @staticmethod
    def log(func_name, msg="triggered", level=logging.DEBUG) -> None:
        return logger.log(level, f"{func_name}: {msg}")

    async def connect(self) -> None:
        """
        Handle a new WebSocket connection:
        - Join the appropriate simulation room group.
        - Load the simulation object.
        - Notify client of simulation status.
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        """Connect to room group based on simulation ID."""
        # Get simulation_id from URL parameters, then
        # Retrieve the simulation object
        self.simulation_id = self.scope["url_route"]["kwargs"]["simulation_id"]
        try:
            self.simulation = await sync_to_async(Simulation.objects.get)(id=self.simulation_id)
        except Simulation.DoesNotExist:
            error_message = f"Simulation with id {self.simulation_id} does not exist."
            ChatConsumer.log(func_name, error_message, level=logging.ERROR)
            logger.exception("Failed to connect: Simulation ID not found")
            await self.accept()  # Accept before sending
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "error",
                        "message": error_message,
                        "redirect": reverse("chatlab:index"),
                    },
                    default=json_default,
                )
            )
            # Socket must be accepted before sending.
            await self.close(code=4004)
            return

        self.room_name = f"simulation_{self.simulation_id}"
        self.room_group_name = self.room_name

        # Join the room group for broadcasting input
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        ChatConsumer.log(
            func_name=func_name,
            msg=f"User {func_name}ed to room {self.room_group_name} (channel: {self.channel_name})",
        )

        # Check if the simulation is new (i.e., no input already exist), then
        # Send connect an init message, then, if new simulation,
        # Simulate System User typing
        is_new_simulation = not await Message.objects.filter(
            simulation=self.simulation_id
        ).aexists()

        ChatConsumer.log(
            func_name=func_name,
            msg=f"sending connect init message for {'new' if is_new_simulation else 'existing'} simulation (#{self.simulation_id})",
        )

        # Send the client a message with initial setup information
        await self.send(
            text_data=json.dumps(
                {
                    "type": "init_message",
                    "sim_display_name": self.simulation.sim_patient_display_name,
                    "sim_display_initials": self.simulation.sim_patient_initials,
                    "new_simulation": is_new_simulation,
                },
                default=json_default,
            )
        )

        # Simulate sim patient typing to the client
        if is_new_simulation and self.simulation.status == Simulation.SimulationStatus.IN_PROGRESS:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "user_typing",
                    "user": SYSTEM_USER,
                    "display_initials": self.simulation.sim_patient_initials,
                },
            )

    async def disconnect(self, close_code: int) -> None:
        """
        Handle WebSocket disconnection and clean up the room group.

        :param close_code: The WebSocket close code
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        ChatConsumer.log(
            func_name=func_name,
            msg=f"User {func_name}ed to room {self.room_group_name} (channel: {self.channel_name})",
        )

    async def receive(self, text_data: str | None = None, bytes_data=None) -> None:
        """
        Handles incoming WebSocket input by parsing the data and routing it to the appropriate
        handler based on the event type.

        This method receives data in either textual or byte format and determines the event type
        represented within the data. Depending on the detected event type, it invokes the corresponding
        handler method to process the event. The method ensures to perform a simulation end check at the
        very beginning to avoid any operations if the simulation has already ended or expired.

        :param text_data: The incoming data in textual format. If provided, it must be a JSON-encoded string.
        :param bytes_data: The incoming data in byte format. This will not be processed in the current implementation.
        :return: None
        """
        func_name = inspect.currentframe().f_code.co_name
        # Parse the incoming data first
        data = json.loads(text_data)
        event_type = data.get("type")
        ChatConsumer.log(func_name, f"{event_type} event received: {data}")

        # Gate by simulation state — only allow lifecycle/typing events after end.
        # Message creation is handled by the REST API with per-conversation locking.
        ended = await self.is_simulation_ended(self.simulation)
        if ended:
            allowed_when_ended = {"client_ready", "typing", "stopped_typing"}
            if event_type not in allowed_when_ended:
                ChatConsumer.log(
                    func_name,
                    f"dropping '{event_type}' because simulation has ended",
                    level=logging.INFO,
                )
                return

        event_dispatch = {
            "client_ready": self.handle_client_ready,
            "simulation.feedback_created": self.handle_generic_event,
            "typing": self.handle_typing,
            "stopped_typing": self.handle_stopped_typing,
            "simulation.metadata.result_created": self.handle_generic_event,
        }

        handler = event_dispatch.get(event_type)
        if handler:
            await handler(data)
        else:
            logger.warning("Unrecognized event type: %s - %s", event_type, data)

    async def handle_client_ready(self, data) -> None:
        """
        Handles the "client_ready" event triggered by the WebSocket client.

        This function is responsible for processing the associated data, including
        handling the preferred content mode and sending the first message in the
        simulation to the WebSocket group, along with relevant metadata like sender's
        user (email), display name, and patient initials.

        :param data: The data associated with the "client_ready" event. It contains the
            configuration and state details needed to process the event.
        :type data: dict

        :return: This function does not return a value. The results of its execution
            are the side effects of interacting with the WebSocket group and sending
            the appropriate message.

        """
        # Set preferred content mode (support both content_mode and contentMode)
        await self.handle_content_mode(data.get("content_mode") or data.get("contentMode"))

    async def is_simulation_ended(self, simulation: Simulation) -> bool:
        """
        Check whether a simulation has ended either by flag or time limit.

        :param simulation: The simulation object to evaluate
        :return: True if the simulation has ended, False otherwise
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        if simulation.is_complete:
            return True

        if (
            simulation.time_limit
            and (simulation.start_timestamp + simulation.time_limit) < timezone.now()
        ):
            await sync_to_async(simulation.mark_timed_out)()

            # Send notification to the user
            await self.channel_layer.group_send(
                f"notifications_{self.scope['user'].id}",
                {
                    "type": "send_notification",
                    "notification": f"Simulation #{simulation.id} has ended.",
                    "notification_type": "simulation-ended",
                },
            )
            return True

        return False

    async def handle_typing(self, data: dict) -> None:
        """
        Broadcast to the group that a user has started typing.

        :param data: Should include 'user' and/or 'display_initials'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        # Notify others in the room that a user is typing
        # Get user from data, or fall back to scope user (convert to string if it's a User object)
        user_ = data.get("user")
        if not user_:
            scope_user = self.scope.get("user")
            user_ = scope_user.email if scope_user and hasattr(scope_user, "email") else SYSTEM_USER

        if data.get("username"):
            logger.warning(
                "data contains `username`: `username` is pending deprecation and should be removed"
            )

        if user_ == SYSTEM_USER:
            display_initials = self.simulation.sim_patient_initials
        else:
            display_initials = data.get("display_initials") or await sync_to_async(
                get_user_initials
            )(user_)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_typing",
                "user": user_,
                "display_initials": display_initials,
                "conversation_id": data.get("conversation_id"),
            },
        )

    async def handle_generic_event(self, data: dict) -> None:
        """
        Handles a system event by sending the provided data to a specific group in the channel layer.

        This method is intended to be used for broadcasting system events to all members of a
        designated group. The provided data dictionary is sent to the `room_group_name` associated
        with the instance.

        :param data: The dictionary containing event data to be sent to the group.
        :type data: dict
        :return: None
        :rtype: None
        """
        await self.channel_layer.group_send(self.room_group_name, {**data})

    async def handle_stopped_typing(self, data: dict) -> None:
        """
        Broadcast to the group that a user has stopped typing.

        :param data: Should include 'user'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        # Notify others in the room that a user has stopped typing
        # Get user from data, or fall back to scope user (convert to string if it's a User object)
        user_ = data.get("user")
        if not user_:
            scope_user = self.scope.get("user")
            user_ = scope_user.email if scope_user and hasattr(scope_user, "email") else SYSTEM_USER

        if data.get("username"):
            logger.warning(
                "data contains `username`: `username` is pending deprecation and should be removed"
            )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_stopped_typing",
                "user": user_,
                "conversation_id": data.get("conversation_id"),
            },
        )

    async def handle_content_mode(self, content_mode: str | None = None) -> None:
        """
        Handles the mode of content presentation by setting it to the provided value
        or falling back to a default value. This function ensures the provided content
        mode is valid, otherwise defaults to `ContentMode.HTML`.

        :param content_mode: The mode of content presentation, provided as a string.
            Defaults to `None`, which will result in using `ContentMode.HTML`.
        :type content_mode: str, optional

        :return: None
        """
        try:
            self.content_mode = ContentMode(content_mode or ContentMode.HTML)
        except ValueError:
            self.content_mode = ContentMode.HTML

    async def simulate_system_typing(self, display_initials: str, started: bool = True) -> None:
        """
        Simulate the system user beginning or stopping typing.

        :param display_initials: Initials to show in the typing indicator
        :param started: True for typing start_timestamp, False for stop
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(
            func_name,
            f"user {display_initials} to {'typing' if started else 'stopped_typing'}",
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_typing" if started else "user_stopped_typing",
                "user": SYSTEM_USER,
                "display_initials": display_initials,
            },
        )

    async def user_typing(self, event: dict) -> None:
        """
        Handle 'user_typing' event by sending data to the client.

        :param event: Dict with 'user', 'display_initials', etc.
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "typing",
                    "user": event.get("user", "unknown"),
                    "display_name": event.get("display_name", "Unknown"),
                    "display_initials": event.get("display_initials", "Unk"),
                    "conversation_id": event.get("conversation_id"),
                },
                default=json_default,
            )
        )

    async def user_stopped_typing(self, event: dict) -> None:
        """
        Handle 'user_stopped_typing' event and notify client.

        :param event: Dict with 'usern'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "stopped_typing",
                    "user": event.get("user", "unknown"),
                    "conversation_id": event.get("conversation_id"),
                },
                default=json_default,
            )
        )

    async def simulation_feedback_created(self, event: dict) -> None:
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(text_data=json.dumps(event, default=json_default))

    async def chat_message_created(self, event: dict) -> None:
        """
        Handles incoming message events.

        This method is triggered when a message event occurs and can be
        used to process or respond to the incoming event. It is an asynchronous
        method and does not return any value. The event parameter provides the
        details of the message event being handled.

        :param event: A dictionary containing information about the message
            event. It may include various keys relevant to the message, such as
            sender details, message content, timestamps, etc.
        :type event: dict
        :return: None
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        # Check if 'content' or `media` exists in the event
        content = event.get("content")
        media = event.get("media") or event.get("media_list") or event.get("mediaList")
        if content is None and media is None:
            ChatConsumer.log(
                func_name,
                msg="at least one of the following must provided, but was not found: `content`, `media`",
                level=logging.ERROR,
            )
            return

        # Proceed to send the message if 'content' exists
        await self.send(text_data=json.dumps(event, default=json_default))

    async def message_status_update(self, event: dict) -> None:
        """
        Send a status update to the WebSocket client for a message.

        :param event: Dict with message ID and new status
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "message_status_update",
                    "id": event["id"],
                    "status": event["status"],
                    "retryable": event.get("retryable"),
                    "error_code": event.get("error_code"),
                    "error_text": event.get("error_text"),
                },
                default=json_default,
            )
        )

    async def simulation_metadata_results_created(self, event: dict) -> None:
        """Receive simulation metadata results created event and send to client."""
        await self.send(text_data=json.dumps(event, default=json_default))

    async def outbox_event(self, event: dict) -> None:
        """Handle outbox events delivered by the drain worker.

        This handler receives events from the outbox drain worker and forwards
        them to connected WebSocket clients with the standardized envelope format.

        The event dict contains:
            - event: The WebSocket envelope with event_id, event_type, created_at,
                    correlation_id, and payload

        :param event: Dict containing the WebSocket envelope
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        envelope = event.get("event", {})

        # Validate envelope has required fields
        if not envelope.get("event_type"):
            ChatConsumer.log(
                func_name,
                msg="outbox event missing event_type",
                level=logging.WARNING,
            )
            return

        if envelope.get("event_type") == "chat.message_created":
            from apps.chatlab.media_payloads import build_message_media_payload, payload_message_id

            payload = dict(envelope.get("payload") or {})
            msg_id = payload_message_id(payload)
            if msg_id is not None:
                try:
                    message = await Message.objects.prefetch_related("media").aget(
                        id=msg_id,
                        simulation_id=self.simulation_id,
                    )
                    headers = dict(self.scope.get("headers", []))
                    host = headers.get(b"host", b"").decode() or None
                    scheme = self.scope.get("scheme", "http")
                    payload.update(
                        build_message_media_payload(
                            message,
                            scheme=scheme,
                            host=host,
                        )
                    )
                except Message.DoesNotExist:
                    payload.setdefault("media_list", [])
                    payload.setdefault("mediaList", [])
            envelope = {**envelope, "payload": payload}

        # Forward the envelope to the client
        await self.send(text_data=json.dumps(envelope, default=json_default))

    @staticmethod
    def build_envelope(
        event_type: str,
        payload: dict,
        event_id: str | None = None,
        correlation_id: str | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Build a standardized WebSocket event envelope.

        All WebSocket events should use this format for consistency and
        client-side deduplication.

        Args:
            event_type: Event type (e.g., 'message.created', 'typing')
            payload: Event payload data
            event_id: Unique event ID (generated if not provided)
            correlation_id: Request correlation ID for tracing
            created_at: ISO timestamp (generated if not provided)

        Returns:
            Standardized envelope dict
        """
        return {
            "event_id": event_id or str(uuid.uuid4()),
            "event_type": event_type,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "correlation_id": correlation_id,
            "payload": payload,
        }
