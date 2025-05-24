# chatlab/utils.py
import inspect
import logging
import threading

from asgiref.sync import async_to_sync, sync_to_async
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.utils.timezone import now

from chatlab.models import ChatSession, MessageMediaLink, Message
from core.utils import get_or_create_system_user, remove_null_keys
from simai.client import SimAIService
from simcore.models import Simulation, SimulationImage
from simcore.utils import generate_fake_name, get_user_initials

logger = logging.getLogger(__name__)


def create_new_simulation(user, modifiers: list=None):
    """Create a new Simulation and ChatSession, and trigger AI patient intro."""
    # Create base Simulation
    simulation = Simulation.objects.create(
        user=user,
        lab="chatlab",
        sim_patient_full_name=generate_fake_name(),
        modifiers=modifiers
    )

    # Link ChatLab extension
    ChatSession.objects.create(simulation=simulation)

    # Get System user
    system_user = get_or_create_system_user()

    # Generate an initial message in background
    ai = SimAIService()

    def start_initial_response(sim):
        logger.debug(f"[chatlab] requesting initial SimMessage for Sim#{sim.id}")
        try:
            sim_responses = async_to_sync(ai.generate_patient_initial)(sim, False)
            channel_layer = get_channel_layer()
            for message in sim_responses:
                async_to_sync(channel_layer.group_send)(
                    f"simulation_{sim.id}",
                    {
                        "type": "chat_message",
                        "content": message.content,
                        "display_name": sim.sim_patient_display_name,
                    },
                )
        except Exception as e:
            logger.exception(f"Initial message generation failed for Sim#{sim.id}: {e}")

    threading.Thread(target=start_initial_response, args=(simulation,), daemon=True).start()

    return simulation

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

async def broadcast_message(message: Message or int, status: str=None):
    """Broadcasts a message to all connected clients."""
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