# chatlab/utils.py
import inspect
import logging

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.utils.timezone import now

from apps.chatlab.media_payloads import build_chat_message_event_payload
from apps.chatlab.models import ChatSession, Message, MessageMediaLink
from apps.common.orm_mode import must_be_async
from apps.common.utils import remove_null_keys
from apps.simcore.models import (
    LabResult,
    RadResult,
    Simulation,
    SimulationMetadata,
)
from apps.simcore.utils import generate_fake_name

from .apps import ChatLabConfig

logger = logging.getLogger(__name__)

APP_NAME = ChatLabConfig.name or ChatLabConfig.label or "<unknown>"


async def await_if_needed(result):
    if inspect.isawaitable(result):
        return await result
    return result


async def create_new_simulation(
    user, modifiers: list | None = None, force: bool = False
) -> Simulation:
    """Create a new Simulation and ChatSession, and trigger celery task to get initial message(simulation)."""
    must_be_async()
    user_label = getattr(user, "email", f"user#{getattr(user, 'id', 'unknown')}")
    logger.debug(
        f"received request to create new simulation for {user_label!r} "
        f"with modifiers {modifiers!r} (force {force!r})"
    )

    sim_patient_full_name = await generate_fake_name()

    simulation = None
    try:
        # Create base Simulation
        simulation = await Simulation.abuild(
            user=user,
            app_=APP_NAME,
            sim_patient_full_name=sim_patient_full_name,
            modifiers=modifiers,
        )
        logger.debug(f"simulation #{simulation.id} created")

        # Link ChatLab extension
        session: ChatSession = await ChatSession.objects.acreate(simulation=simulation)
        logger.debug(f"chatlab session #{session.id} linked simulation #{simulation.id}")

        # Create the patient conversation for this simulation
        from apps.simcore.models import Conversation, ConversationType

        patient_type = await ConversationType.objects.aget(slug="simulated_patient")
        patient_conv = await Conversation.objects.acreate(
            simulation=simulation,
            conversation_type=patient_type,
            display_name=simulation.sim_patient_display_name,
            display_initials=simulation.sim_patient_initials or "Unk",
        )
        logger.debug(
            "patient conversation #%s created for simulation #%s",
            patient_conv.id,
            simulation.id,
        )
    except Exception:
        logger.exception("Failed while provisioning a new simulation")
        if simulation is not None:
            await simulation.adelete()
        raise

    # Enqueue initial AI response (fire-and-forget)
    from .orca.services import GenerateInitialResponse

    try:
        call_id = await GenerateInitialResponse.task.using(
            context={
                "simulation_id": simulation.id,
                "user_id": user.id,
                "conversation_id": patient_conv.id,
            }
        ).aenqueue()
    except Exception:
        logger.exception("Initial generation enqueue failed for simulation %s", simulation.id)
        await sync_to_async(simulation.mark_failed)(
            reason_code="initial_generation_enqueue_failed",
            reason_text="We could not start this simulation. Please try again.",
            retryable=True,
        )
        return simulation

    logger.info(
        "Simulation %s created, initial response enqueued as call %s", simulation.id, call_id
    )

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
    return MessageMediaLink.objects.get_or_create(message_id=message_id, media_id=media_id)


async def socket_send(
    __type: str,
    __group: str | None = None,
    __simulation_id: int | None = None,
    __payload: dict | None = None,
    __status: str | None = None,
    **kwargs,
) -> None:
    """
    Legacy direct WebSocket sender for transient hints only.

    :param __payload: Dict payload to send over the socket.
    :param __group: The socket group name (typically tied to the simulation ID).
    :param __type: The type of payload to send.
    :param __status: Optional status string for logging/debugging purposes.
    :param __simulation_id: Optional simulation ID to use for group generation
    :param kwargs: Additional keyword arguments to pass to the `group_send` method.
    """
    durable_event_types = {
        "chat.message_created",
        "message_status_update",
        "simulation.state_changed",
    }
    if __type in durable_event_types:
        logger.warning(
            "socket_send called for durable event %s; prefer outbox delivery instead",
            __type,
        )

    # Build group name from apps.simcore ID if group not provided
    if __group is None:
        logger.debug(
            f"Group not provided. Attempting to use simulation ID (provided '{__simulation_id}')."
        )
        if await Simulation.objects.filter(id=__simulation_id).aexists():
            __group = f"simulation_{__simulation_id}"
            logger.debug(f"Simulation found. Using '{__group}' as group name.")
        else:
            raise ObjectDoesNotExist(
                f"No group provided and Simulation with ID '{__simulation_id}' was not found."
            )

    logger.info(f"[socket_send] received new '{__type}' event for group '{__group}'.")

    channel_layer = get_channel_layer()

    event = {
        "type": __type,
        "status": __status,
        **__payload,
    }

    try:
        await channel_layer.group_send(__group, event)
    except Exception as e:
        logger.error(msg=f"socket_send failed: {e}")

    logger.debug(f"'{__type}': broadcasted to group '{__group}'\n\t\tEvent payload: {__payload}")
    return


async def broadcast_event(
    __type: str,
    __simulation: Simulation | int,
    __payload: dict | None = None,
    __status: str | None = None,
    **kwargs,
) -> None:
    """Broadcasts an event to the specified group layer.

    Uses `socket_send` to send the event payload to the specified group.

    This function is asynchronous and facilitates communication between
    different components or systems by transmitting payload data, event
    type, and other contextual information. It can also include simulation
    and status details in the transmission.

    :param __payload: The data to be sent within the event.
    :type __payload: dict
    :param __type: The type of the event.
    :type __type: str
    :param __simulation: An instance of `Simulation` or its identifier, which
        determines the group to broadcast to.
    :type __simulation: Simulation | int, optional
    :param __status: The status associated with the event. Defaults to None.
    :type __status: str, optional
    :param kwargs: Additional keyword arguments that might be required by
        `socket_send`.
    :return: None
    :rtype: None
    """
    if __payload is None:
        __payload = {}

    if isinstance(__simulation, Simulation):
        __simulation = __simulation.id

    await socket_send(
        __payload=__payload,
        __type=__type,
        __simulation_id=__simulation,
        __status=__status,
        **kwargs,
    )
    return


async def broadcast_patient_results(
    __source: list[LabResult | RadResult | SimulationMetadata] | LabResult | RadResult | int,
    __status: str | None = None,
) -> None:
    """Broadcasts a patient results event to the specified group layer.

    Uses `socket_send` to send the event payload to the specified group.

    :param __source: Result source. One of: int (pk), QuerySet, list, LabResult, RadResult.
    :param __status:
    :return:
    """
    if not __source:
        logger.warning("No source instances provided. Skipping broadcast...")
        return

    # Get the instance if provided ID as the source
    if isinstance(__source, int):
        __source = await SimulationMetadata.objects.aget(id=__source)

    # Convert to list if not already a list, tuple, or QuerySet
    if not isinstance(__source, (list, tuple, QuerySet)):
        __source = [__source]

    # Debug logging
    logger.debug(f"Received {len(__source)} patient results to broadcast to all connected clients.")

    # Group results by simulation ID and serialize them before broadcasting
    grouped_results = {}
    skipped = 0

    for result in list(__source):
        sim_id = result.simulation_id

        # Serialize the result object and add it to the group layer results list
        try:
            serialized = result.serialize()
        except AttributeError as e:
            logger.error(f"{type(result).__name__} object has no .serialize() method: {e}")
            skipped += 1
            continue

        grouped_results.setdefault(sim_id, []).append(serialized)

    if skipped:
        logger.warning(f"Skipped {skipped} results due to missing .serialize() method.")

    # Broadcast results to each simulation group layer
    for sim_id in grouped_results:
        payload = {"tool": "patient_results", "results": grouped_results[sim_id]}

        # Send event to the group layer
        logger.debug(f"Broadcasting {len(grouped_results[sim_id])} results to simulation_{sim_id}")
        await socket_send(
            __type="simulation.metadata.results_created",
            __payload=payload,
            __status=__status,
            __simulation_id=sim_id,
        )
    return


async def broadcast_message(
    message: Message | int,
    status: str | None = None,
    **kwargs,
) -> None:
    """Legacy compatibility wrapper that now routes durable message events via outbox."""
    from apps.common.outbox import enqueue_event_sync, poke_drain_sync

    # Get Message instance if provided ID
    if not isinstance(message, Message):
        try:
            message = (
                await Message.objects.select_related("sender")
                .prefetch_related("media")
                .aget(id=message)
            )
        except Message.DoesNotExist:
            logger.error(msg=f"Message ID {message} not found. Skipping broadcast.")
            return None

    payload = build_chat_message_event_payload(
        message,
        status=status,
        fallback_conversation_type="simulated_patient",
    )
    payload = await sync_to_async(remove_null_keys)(payload)
    event = await sync_to_async(enqueue_event_sync)(
        event_type="chat.message_created",
        simulation_id=message.simulation_id,
        payload=payload,
        idempotency_key=f"chat.message_created:{message.id}",
    )
    if event:
        await sync_to_async(poke_drain_sync)()
    return None
