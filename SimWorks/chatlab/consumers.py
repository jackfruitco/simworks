import inspect
import json
import logging
import warnings
from enum import Enum

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import reverse
from django.utils import timezone

from simcore.models import Simulation
from simcore.utils import get_user_initials
from .models import Message
from .models import RoleChoices

logger = logging.getLogger(__name__)


class ContentMode(str, Enum):
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
            self.simulation = await sync_to_async(Simulation.objects.get)(
                id=self.simulation_id
            )
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
                    }
                )
            )
            # Socket must be accepted before sending.
            await self.close(code=4004)
            return

        self.room_name = f"simulation_{self.simulation_id}"
        self.room_group_name = self.room_name

        # Join the room group for broadcasting messages
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        ChatConsumer.log(
            func_name=func_name,
            msg=f"User {func_name}ed to room {self.room_group_name} (channel: {self.channel_name})",
        )

        # Check if the simulation is new (i.e., no messages already exist), then
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
                }
            )
        )

        # Simulate sim patient typing to the client
        if is_new_simulation:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "user_typing",
                    "username": "System",
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

    async def receive(self, text_data: str = None, bytes_data=None) -> None:
        """
        Handles incoming WebSocket messages by parsing the data and routing it to the appropriate
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

        # Gate by simulation state
        ended = await self.is_simulation_ended(self.simulation)
        if ended:
            # Always allow lightweight client lifecycle and typing signals
            allowed_when_ended = {"client_ready", "typing", "stopped_typing"}
            # Also allow instructor/feedback messages to continue after end
            is_feedback_chat = event_type == "chat.message_created" and data.get("feedbackConversation") is True
            if event_type not in allowed_when_ended and not is_feedback_chat:
                ChatConsumer.log(func_name, f"dropping '{event_type}' because simulation has ended", level=logging.INFO)
                return

        event_dispatch = {
            "client_ready": self.handle_client_ready,
            "chat.message_created": self.handle_message,
            "simulation.feedback_created": self.handle_generic_event,
            "typing": self.handle_typing,
            "stopped_typing": self.handle_stopped_typing,
            "simulation.metadata.result_created": self.handle_generic_event,
        }

        handler = event_dispatch.get(event_type)
        if handler:
            await handler(data)
        else:
            warnings.warn(f"Unrecognized event type: {event_type} – {data}")

    async def handle_client_ready(self, data) -> None:
        """
        Handles the "client_ready" event triggered by the WebSocket client.

        This function is responsible for processing the associated data, including
        handling the preferred content mode and sending the first message in the
        simulation to the WebSocket group, along with relevant metadata like sender's
        username, display name, and patient initials.

        :param data: The data associated with the "client_ready" event. It contains the
            configuration and state details needed to process the event.
        :type data: dict

        :return: This function does not return a value. The results of its execution
            are the side effects of interacting with the WebSocket group and sending
            the appropriate message.

        """
        # Set preferred content mode (support both content_mode and contentMode)
        await self.handle_content_mode(data.get("content_mode") or data.get("contentMode"))

    async def _generate_patient_response(self, user_msg: Message) -> None:
        """Generate patient response."""
        from .ai.services import GenerateReplyResponse
        GenerateReplyResponse().execute(simulation=self.simulation.pk, user_msg=user_msg)


    async def _generate_stitch_response(self, user_msg: Message) -> None:
        """Generate a response from Stitch for feedback conversations."""
        raise NotImplementedError
        from .ai.services import GenerateStitchResponse
        GenerateStitchResponse.run_all(simulation=self.simulation.pk, user_msg=user_msg)

        return await acall_connector(
            generate_hotwash_response,
            simulation_id=self.simulation.pk,
            user_msg=user_msg,
            enqueue=False
        )

    async def is_simulation_ended(self, simulation: Simulation) -> bool:
        """
        Check whether a simulation has ended either by flag or time limit.

        :param simulation: The simulation object to evaluate
        :return: True if the simulation has ended, False otherwise
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        if simulation.end_timestamp:
            return True

        if (
                simulation.time_limit
                and (simulation.start_timestamp + simulation.time_limit) < timezone.now()
        ):
            simulation.end_timestamp = timezone.now()
            await sync_to_async(simulation.save)()

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

    async def handle_message(self, data: dict) -> None:
        """
        Handle incoming user messages, save them to DB, and trigger AI response.

        :param data: A dict containing at least 'content' and 'role'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        # TODO deprecation warning
        if data.get("event_type") in {"message", "chat.message"}:
            warnings.warn(
                "'message' event_type is deprecated. Use 'chat.message' instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        is_from_user = data.get("role", "").upper() == "USER"

        content = data["content"]
        sender = self.scope["user"]

        if is_from_user:
            # Save user message to the database
            simulation = await sync_to_async(Simulation.objects.get)(
                id=self.simulation_id
            )
            user_msg = await self.save_message(
                simulation=simulation,
                sender=sender,
                content=content,
                role=RoleChoices.USER,
            )

            # Simulate the user message as delivered once saved to the database
            # TODO [FEAT]: consider v0.8.1
            # await self.broadcast_message_status(user_msg.id, "delivered")

            feedback_conversation = data.get("feedbackConversation")
            logger.debug(f"Consumer received message with conversation type: {feedback_conversation}")

            if feedback_conversation:
                await self._generate_stitch_response(user_msg)
                return

            await self._generate_patient_response(user_msg)

    async def handle_typing(self, data: dict) -> None:
        """
        Broadcast to the group that a user has started typing.

        :param data: Should include 'username' and/or 'display_initials'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        # Notify others in the room that a user is typing
        username = data.get("username") or self.scope.get("user") or "System"
        if username == "System":
            display_initials = self.simulation.sim_patient_initials
        else:
            display_initials = data.get("display_initials") or await sync_to_async(
                get_user_initials
            )(username)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_typing",
                "username": username,
                "display_initials": display_initials,
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

        :param data: Should include 'username'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        # Notify others in the room that a user has stopped typing
        username = data.get("username") or self.scope.get("user") or "System"

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_stopped_typing",
                "username": username,
            },
        )

    async def handle_content_mode(self, content_mode: str = None) -> None:
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

    async def simulate_system_typing(
            self, display_initials: str, started: bool = True
    ) -> None:
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
                "username": "System",
                "display_initials": display_initials,
            },
        )

    @sync_to_async
    def save_message(
            self, simulation: Simulation, sender, content: str, role: str = "A"
    ) -> Message:
        """
        Save a message to the database using the Message model.

        :param simulation: Simulation instance
        :param sender: User instance (or None if System user)
        :param content: Text of the message
        :param role: Role type (USER, ASSISTANT, etc.)
        :return: The created Message instance
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        return Message.objects.create(
            simulation=simulation,
            role=role,
            sender=sender,
            content=content,
        )

    async def user_typing(self, event: dict) -> None:
        """
        Handle 'user_typing' event by sending data to the client.

        :param event: Dict with 'username', 'display_initials', etc.
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "typing",
                    "username": event.get("username", "unknown"),
                    "display_name": event.get("display_name", "Unknown"),
                    "display_initials": event.get("display_initials", "Unk"),
                }
            )
        )

    async def user_stopped_typing(self, event: dict) -> None:
        """
        Handle 'user_stopped_typing' event and notify client.

        :param event: Dict with 'username'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "stopped_typing",
                    "username": event.get("username", "unknown"),
                }
            )
        )

    async def simulation_feedback_created(self, event: dict) -> None:
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(func_name)

        await self.send(text_data=json.dumps(event))

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
        media = event.get("media")
        if content is None and media is None:
            ChatConsumer.log(
                func_name,
                msg="at least one of the following must provided, but was not found: `content`, `media`",
                level=logging.ERROR,
            )
            return

        # Proceed to send the message if 'content' exists
        await self.send(text_data=json.dumps(event))

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
                }
            )
        )

    async def simulation_metadata_results_created(self, event: dict) -> None:
        """Receive simulation metadata results created event and send to client."""
        await self.send(text_data=json.dumps(event))
