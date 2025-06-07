# chatlab/utils.py
import inspect
import logging
import threading
import warnings

from asgiref.sync import async_to_sync, sync_to_async
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.db.models import QuerySet
from django.utils.timezone import now

from chatlab.models import ChatSession, MessageMediaLink, Message
from core.utils import get_or_create_system_user, remove_null_keys
from simai.client import SimAIClient
from simcore.models import Simulation, SimulationImage, RadResult, LabResult, SimulationMetadata
from simcore.utils import generate_fake_name, get_user_initials

logger = logging.getLogger(__name__)


async def create_new_simulation(user, modifiers: list=None):
    """Create a new Simulation and ChatSession, and trigger AI patient intro."""

    sim_patient_full_name = await generate_fake_name()

    # Create base Simulation
    simulation = await Simulation.abuild(
        user=user,
        lab="chatlab",
        sim_patient_full_name=sim_patient_full_name,
        modifiers=modifiers
    )

    # Link ChatLab extension
    await ChatSession.objects.acreate(simulation=simulation)

    # Get System user
    system_user = await get_or_create_system_user()

    # Generate an initial message
    logger.debug(f"[chatlab] requesting initial SimMessage for Sim#{simulation.id}")
    try:
        client = SimAIClient()
        sim_responses = await client.generate_patient_initial(simulation, False)
        channel_layer = get_channel_layer()
        for message in sim_responses:
            await channel_layer.group_send(
                f"simulation_{simulation.id}",
                {
                    "type": "chat_message",
                    "content": message.content,
                    "display_name": simulation.sim_patient_display_name,
                },
            )
    except Exception as e:
        logger.exception(f"Initial message generation failed for Sim#{simulation.id}: {e}")

    return simulation

@database_sync_to_async
def maybe_start_simulation(simulation):
    """Starts the simulation if not already started."""
    "TODO add `force: bool=False` to force restart a simulation"
    if simulation.start_timestamp is None:
        simulation.start_timestamp = now()
        simulation.save(update_fields=["start_timestamp"])

@database_sync_to_async
def add_message_media(message_id, media_id):
    """Adds a media object to a message."""
    return MessageMediaLink.objects.get_or_create(
        message_id=message_id,
        media_id=media_id
    )
async def socket_send(
        payload: dict,
        group: str,
        type: str,
        event: str,
        status: str = None
) -> None:
    """
    Sends an arbitrary payload to the specified WebSocket group.

    :param payload: Dict payload to send over the socket.
    :param group: The socket group name (typically tied to the simulation ID).
    :param type: The type of payload to send.
    :param event: Custom event type name for front-end handling (e.g., 'message', 'patient_result').
    :param status: Optional status string for logging/debugging purposes.
    """
    logger.debug(
        f"`socket_send` received a {type} payload for a(n) {event} "
        f"event to {group} group. Payload preview: {payload[:20]}"
    )

    channel_layer = get_channel_layer()

    # Add type, event, and status to the payload
    payload.update({
        "type": type,
        "event": event,
        "status": status,
    })

    try:
        await channel_layer.group_send(group, payload)
    except Exception as e:
        logger.error(msg=f"socket_send failed: {e}")


    logger.info(f"'{type}':'{event}' broadcasted to group '{group}'")
    logger.debug(f"Event payload: {payload}")
    return

async def broadcast_patient_results(
        __source: QuerySet | list | LabResult | RadResult or int,
        __status: str=None) -> None:
    """
    Broadcast patient results to all connected clients using `socket_send`.

    :param __source: Result source. One of: int (pk), QuerySet, list, LabResult, RadResult.
    :param __status:
    :return:
    """
    if isinstance(__source, int):
        __source = await sync_to_async(SimulationMetadata.objects.get)(id=__source)

    if not isinstance(__source, (QuerySet, list)):
        __source = [__source]

    grouped_results = {}
    for result in list(__source):
        sim_id = result.simulation_id
        grouped_results.setdefault(sim_id, []).append(result.serialize())

    for sim_id in grouped_results:
        payload = {
            "results": grouped_results[sim_id]
        }

        # Set channel and group layers to broadcast to
        group = f"simulation_{sim_id}"

        await socket_send(
            payload=payload,
            group=group,
            type="sim.metadata",
            event="patient_result",
            status=__status
        )
    return

async def broadcast_message(message: Message or int, status: str=None) -> None:
    """Broadcast a message to all connected client via `socket_send`."""
    # Get Message instance if provided ID
    if not isinstance(message, Message):
        try:
            message = await sync_to_async(Message.objects.get)(id=message)
        except Message.DoesNotExist:
            logger.error(msg=f"Message ID {message} not found. Skipping broadcast.")
            return

    # Get Simulation instance from Message FK
    try:
        simulation = await sync_to_async(Simulation.objects.get)(id=message.simulation_id)
    except Simulation.DoesNotExist:
        logger.error(msg=f"Simulation ID {message.simulation_id} not found. Skipping broadcast.")
        return

    # Set channel and group layers to broadcast to
    channel_layer = get_channel_layer()
    group = f"simulation_{message.simulation_id}"

    has_sender = message.sender is not None
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
        display_name = simulation.sim_patient_display_name
        display_initials = simulation.sim_patient_initials

    media_list = await sync_to_async(lambda: list(message.media.all()))()
    _media = [
        {
            "id": media.id,
            "url": media.thumbnail.url,
         }
        for media in media_list
    ]

    payload = {
        "id": message.id,
        "role": message.role,
        "content": message.content or None,
        "media": [m["id"] for m in _media] or None,
        "mediaList": _media or None,
        "timestamp": message.timestamp.isoformat(),
        "status": status or None,
        "messageType": message.message_type,
        "senderId": sender_username or None,
        "displayName": display_name or None,
        "displayInitials": display_initials or None,
        "isFromAi": message.is_from_ai or None,
    }
    payload = await sync_to_async(remove_null_keys)(payload)

    return await socket_send(payload=payload, group=group, type="chat.message", event="message")

async def broadcast_chat_message(message: Message or int, status: str=None):
    """Broadcasts a message to all connected clients."""
    warnings.warn(DeprecationWarning("Use `broadcast_message` instead."))

    func_name = inspect.currentframe().f_code.co_name

    async def _log(level=logging.DEBUG, msg=''):
        logger.log(level=level, msg=f"[{func_name}]: {msg}")

    # Get Message instance if provided ID
    if not isinstance(message, Message):
        try:
            message = await sync_to_async(Message.objects.get)(id=message)
        except Message.DoesNotExist:
            await _log(level=logging.ERROR, msg=f"Message ID {message} not found. Skipping broadcast.")
            return

    # Get Simulation instance from Message FK
    try:
        simulation = await sync_to_async(Simulation.objects.get)(id=message.simulation_id)
    except Simulation.DoesNotExist:
        await _log(level=logging.ERROR, msg=f"Simulation ID {message.simulation_id} not found. Skipping broadcast.")
        return

    await _log(
        msg=f"Broadcasting message #{message.id} (Sim#{message.simulation.id}, MsgType={message.message_type}) to all connected clients."
    )

    # Set channel and group layers to broadcast to
    channel_layer = get_channel_layer()
    group = f"simulation_{message.simulation_id}"

    has_sender = message.sender is not None
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
        display_name = simulation.sim_patient_display_name
        display_initials = simulation.sim_patient_initials

    media_list = await sync_to_async(lambda: list(message.media.all()))()
    _media = [
        {
            "id": media.id,
            "url": media.thumbnail.url,
         }
        for media in media_list
    ]

    payload = {
        "type": "chat.message",
        "id": message.id,
        "role": message.role,
        "content": message.content or None,
        "media": [m["id"] for m in _media] or None,
        "mediaList": _media or None,
        "timestamp": message.timestamp.isoformat(),
        "status": status or None,
        "messageType": message.message_type,
        "senderId": sender_username or None,
        "displayName": display_name or None,
        "displayInitials": display_initials or None,
        "isFromAi": message.is_from_ai or None,
    }
    payload = await sync_to_async(remove_null_keys)(payload)

    try:
        await channel_layer.group_send(group, payload)
    except Exception as e:
        await _log(level=logging.ERROR, msg=f"broadcast failed: {e}")

    msg = f"'{payload['type']}' message broadcasted to group '{group}'"
    if logger.isEnabledFor(logging.DEBUG):
        msg = f"{msg}  (payload={payload})"
    await _log(level=logging.INFO, msg=msg)