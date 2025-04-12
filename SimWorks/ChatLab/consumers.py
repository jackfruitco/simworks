import asyncio
import inspect
import json
import logging
import random
import time
from logging import DEBUG
from logging import ERROR
from logging import INFO

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from core.SimAI.async_client import AsyncOpenAIChatService
from core.utils import get_user_initials
from django.urls import reverse
from django.utils import timezone

from .models import Message
from .models import RoleChoices
from .models import Simulation

logger = logging.getLogger(__name__)
ai = AsyncOpenAIChatService()


class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.simulation_id = None
        self.room_name = None
        self.room_group_name = None
        self.simulation = None

    def log(self, func_name, msg="triggered", level=DEBUG) -> None:
        return logger.log(level, f"{func_name}: {msg}")

    async def connect(self) -> None:
        """
        Handle a new WebSocket connection:
        - Join the appropriate simulation room group.
        - Load the simulation object.
        - Notify client of simulation status.
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        """Connect to room group based on simulation ID."""
        # Get simulation_id from URL parameters, then
        # Retrieve simulation object
        self.simulation_id = self.scope["url_route"]["kwargs"]["simulation_id"]
        try:
            self.simulation = await sync_to_async(Simulation.objects.get)(
                id=self.simulation_id
            )
        except Simulation.DoesNotExist:
            error_message = f"Simulation with id {self.simulation_id} does not exist."
            ChatConsumer.log(self, func_name, error_message, level=ERROR)
            # Send an error message to the client before closing
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "error",
                        "message": error_message,
                        "redirect": reverse("ChatLab:index"),
                    }
                )
            )
            await self.close(code=4004)
            return

        self.room_name = f"simulation_{self.simulation_id}"
        self.room_group_name = self.room_name

        # Join the room group for broadcasting messages
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        ChatConsumer.log(
            self=self,
            func_name=func_name,
            msg=f"User {func_name}ed to room {self.room_group_name} (channel: {self.channel_name})",
        )

        # Check if simulation is new (i.e. no messages already exist), then
        # Send connect init message, then, if new simulation,
        # Simulate System User typing.
        new_simulation = not await sync_to_async(
            Message.objects.filter(simulation=self.simulation_id).exists
        )()
        ChatConsumer.log(
            self=self,
            func_name=func_name,
            msg=f"sending connect init message for {'new' if new_simulation else 'existing'} simulation (SIM:{self.simulation_id})",
        )
        await self.send(
            text_data=json.dumps(
                {
                    "type": "init_message",
                    "sim_display_name": self.simulation.sim_patient_display_name,
                    "sim_display_initials": self.simulation.sim_patient_initials,
                    "new_simulation": new_simulation,
                }
            )
        )

        if new_simulation:
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
        ChatConsumer.log(self, func_name)

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        ChatConsumer.log(
            self=self,
            func_name=func_name,
            msg=f"User {func_name}ed to room {self.room_group_name} (channel: {self.channel_name})",
        )

    async def receive(self, text_data: str) -> None:
        """
        Receive a message from the WebSocket and dispatch based on event type.

        :param text_data: Raw JSON string sent from the client
        """
        func_name = inspect.currentframe().f_code.co_name

        # simulation = await sync_to_async(Simulation.objects.get)(id=self.simulation_id)

        # Check if simulation has ended or timed out
        if await self.is_simulation_ended(self.simulation):
            return

        # Parse the incoming data
        data = json.loads(text_data)
        event_type = data.get("type")  # Identify the type of event
        ChatConsumer.log(
            self, func_name, f"{event_type} event received: {data}", level=INFO
        )

        if event_type == "message":
            await self.handle_message(data)
        elif event_type == "typing":
            await self.handle_typing(data)
        elif event_type == "stopped_typing":
            await self.handle_stopped_typing(data)
        elif event_type == "client_ready":
            first_msg = await sync_to_async(
                lambda: Message.objects.filter(simulation=self.simulation)
                .order_by("timestamp")
                .first()
            )()
            if first_msg:
                print("[WebSocket] Received client_ready event")
                print(f"[WebSocket] Sending message to group: {first_msg.content}")
                sender_username = await sync_to_async(
                    lambda: first_msg.sender.username
                )()
                display_name = await sync_to_async(
                    lambda: first_msg.display_name or first_msg.sender.username
                )()
                display_initials = await sync_to_async(
                    lambda: first_msg.simulation.sim_patient_initials
                )()
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat_message",
                        "content": first_msg.content,
                        "sender": sender_username,
                        "display_name": display_name,
                        "display_initials": display_initials,
                        "status": "delivered",
                        "id": str(first_msg.id),
                    },
                )

    async def is_simulation_ended(self, simulation: Simulation) -> bool:
        """
        Check whether a simulation has ended either by flag or time limit.

        :param simulation: The simulation object to evaluate
        :return: True if the simulation has ended, False otherwise
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        if simulation.end:
            return True

        if (
            simulation.time_limit
            and (simulation.start + simulation.time_limit) < timezone.now()
        ):
            simulation.end = timezone.now()
            await sync_to_async(simulation.save)()

            # Send notification to user
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
        ChatConsumer.log(self, func_name)

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

            # Simulate user message as delivered once saved to the database
            await self.broadcast_message_status(user_msg.id, "delivered")
            # await asyncio.sleep(random.uniform(1.0, 4.0))
            # await self.broadcast_message_status(user_msg.id, "read")

            # Simulate System Role player as typing after short delay
            # await asyncio.sleep(random.uniform(1.0, 5.0))
            # await self.simulate_system_typing(simulation.sim_patient_initials)

            # Record start time for typing indicator
            start_time = time.monotonic()
            min_delay_time = random.uniform(3.0, 8.0)

            # Send user's input to OpenAI to generate response, then
            # Wait until the minimum delay time is met
            sim_responses = await ai.generate_patient_reply(user_msg)

            elapsed = time.monotonic() - start_time
            if elapsed < min_delay_time:
                await asyncio.sleep(min_delay_time - elapsed)

            # Simulate System Role player stops typing, then
            # Broadcast System Role player (AI-generated) message
            # await self.simulate_system_typing(simulation.sim_patient_initials, False)

            # Convert sim_responses to a list in a synchronous thread
            sim_responses_list = await sync_to_async(list)(sim_responses)
            # Broadcast each system-generated message
            for message in sim_responses_list:
                await self.broadcast_message(message, status="delivered")

    async def handle_typing(self, data: dict) -> None:
        """
        Broadcast to the group that a user has started typing.

        :param data: Should include 'username' and/or 'display_initials'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

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

    async def handle_stopped_typing(self, data: dict) -> None:
        """
        Broadcast to the group that a user has stopped typing.

        :param data: Should include 'username'
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        # Notify others in the room that a user has stopped typing
        username = data.get("username") or self.scope.get("user") or "System"

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "user_stopped_typing",
                "username": username,
            },
        )

    async def broadcast_message(self, message: Message, status: str = None) -> None:
        """
        Broadcast a message to the room group, handling both user and system messages.

        :param message: Message instance to broadcast
        :param status: Optional message status (e.g., "delivered", "read")
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        has_sender = await sync_to_async(lambda: bool(message.sender_id))()
        if has_sender:
            sender_username = await sync_to_async(lambda: message.sender.username)()
            display_name = await sync_to_async(
                lambda: message.display_name or message.sender.username
            )()
            display_initials = await sync_to_async(
                lambda: get_user_initials(message.sender)
            )()
        else:
            sender_username = "System"
            display_name = self.simulation.sim_patient_display_name
            display_initials = self.simulation.sim_patient_initials

        event = {
            "type": "chat_message",
            "id": str(message.id),
            "sender": sender_username,
            "content": message.content,
            "display_name": display_name,
            "display_initials": display_initials,
        }
        if status:
            event["status"] = status

        await self.channel_layer.group_send(self.room_group_name, event)

    async def broadcast_message_status(
        self, message_id: str | int, status: str
    ) -> None:
        """
        Broadcast a message status change to the room group.

        :param message_id: ID of the message
        :param status: Status to broadcast, e.g., "delivered"
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name, f"message #{message_id} to {status}")

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "message_status_update",
                "id": str(message_id),
                "status": status,
            },
        )

    async def simulate_system_typing(
        self, display_initials: str, started: bool = True
    ) -> None:
        """
        Simulate the system user beginning or stopping typing.

        :param display_initials: Initials to show in the typing indicator
        :param started: True for typing start, False for stop
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(
            self,
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
        :param sender: User instance (or None for system)
        :param content: Text of the message
        :param role: Role type (USER, ASSISTANT, etc.)
        :return: The created Message instance
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        return Message.objects.create(
            simulation=simulation,
            role=role,
            sender=sender,
            content=content,
        )

    async def user_typing(self, event: dict) -> None:
        """
        Handle 'user_typing' event by sending data to client.

        :param event: Dict with 'username', 'display_initials', etc.
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

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
        ChatConsumer.log(self, func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "stopped_typing",
                    "username": event.get("username", "unknown"),
                }
            )
        )

    async def chat_message(self, event: dict) -> None:
        """
        Send a chat message to the WebSocket from the room group.

        :param event: Dict with message metadata and content
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        # Check if 'content' exists in event
        content = event.get("content", None)
        if content is None:
            ChatConsumer.log(self, func_name, "Error! chat_message content is None")
            return

        # Proceed to send the message if 'content' exists
        await self.send(
            text_data=json.dumps(
                {
                    "id": event.get("id"),
                    "type": "chat_message",
                    "status": event.get("status"),
                    "content": content,
                    "display_name": event.get("display_name"),
                    "sender": event.get("sender") or "System",
                }
            )
        )

    async def message_status_update(self, event: dict) -> None:
        """
        Send a status update to the WebSocket client for a message.

        :param event: Dict with message ID and new status
        """
        func_name = inspect.currentframe().f_code.co_name
        ChatConsumer.log(self, func_name)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "message_status_update",
                    "id": event["id"],
                    "status": event["status"],
                }
            )
        )
