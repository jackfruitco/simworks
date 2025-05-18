# chatlab/utils.py

import logging
import threading

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.utils.timezone import now

from chatlab.models import ChatSession, Message, MessageMediaLink
from core.utils import get_or_create_system_user
from simai.async_client import AsyncOpenAIService
from simcore.models import Simulation, SimulationImage
from simcore.utils import generate_fake_name

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

    # Generate initial message in background
    ai = AsyncOpenAIService()

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