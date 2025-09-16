# chatlab/utils.py
import inspect
import logging
import warnings

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from chatlab.models import ChatSession
from chatlab.models import Message
from chatlab.models import MessageMediaLink
from core.utils import remove_null_keys
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.utils.timezone import now
from simcore.models import LabResult
from simcore.models import RadResult
from simcore.models import Simulation
from simcore.models import SimulationMetadata
from simcore.utils import generate_fake_name
from simcore.utils import get_user_initials

logger = logging.getLogger(__name__)


async def create_new_simulation(
    user, modifiers: list = None, force: bool = False
) -> Simulation:
    """Create a new Simulation and ChatSession, and trigger celery task to get initial message(s)."""
    sim_patient_full_name = await generate_fake_name()

    # Create base Simulation
    simulation = await Simulation.abuild(
        user=user,
        lab="chatlab",
        sim_patient_full_name=sim_patient_full_name,
        modifiers=modifiers,
        include_default=True,
    )

    # Link ChatLab extension
    await ChatSession.objects.acreate(simulation=simulation)

    # Generate an initial message
    logger.debug(
        f"Starting celery task to generate initial SimMessage for Sim#{simulation.id}"
    )
    from simai.tasks import generate_patient_initial as task

    task.delay(simulation.id, force)

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
        message_id=message_id, media_id=media_id
    )


async def socket_send(
    __type: str,
    __group: str = None,
    __simulation_id: int = None,
    __payload: dict = None,
    __status: str = None,
    **kwargs,
) -> None:
    """
    Sends an arbitrary payload to the specified WebSocket group.

    :param __payload: Dict payload to send over the socket.
    :param __group: The socket group name (typically tied to the simulation ID).
    :param __type: The type of payload to send.
    :param __status: Optional status string for logging/debugging purposes.
    :param __simulation_id: Optional simulation ID to use for group generation
    :param kwargs: Additional keyword arguments to pass to the `group_send` method.
    """

    # Remove deprecated `__event` kwarg if present
    # TODO deprecation
    if "__event" in kwargs:
        __event = kwargs.pop("__event")
        warnings.warn(
            DeprecationWarning(
                "`__event` is no longer used. Use explicit `__type` instead."
            )
        )

    # Build group name from simulation ID if group not provided
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

    logger.info(f"[socket_send] new '{__type}' event for group '{__group}'.")

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

    logger.debug(f"'{__type}': broadcasted to group '{__group}'")
    logger.debug(f"Event payload: {__payload}")
    return


async def broadcast_event(
    __type: str,
    __simulation: Simulation | int,
    __payload: dict = {},
    __status: str = None,
    **kwargs,
) -> None:
    """
    Broadcasts an event by sending its details to a socket. This function is
    asynchronous and facilitates communication between different components
    or systems by transmitting payload data, event type, and other contextual
    information. It can also include simulation and status details
    in the transmission.

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
    __source:  list[LabResult | RadResult | SimulationMetadata] | LabResult | RadResult or int,
    __status: str = None
) -> None:
    """
    Broadcast patient results to all connected clients using `socket_send`.

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
    logger.debug(
        f"Received {len(__source)} patient results to broadcast to all connected clients."
    )

    # Group results by simulation ID and serialize them before broadcasting
    grouped_results = {}
    skipped = 0

    for result in list(__source):
        sim_id = result.simulation_id

        # Serialize the result object and add it to the group layer results list
        try:
            serialized = result.serialize()
        except AttributeError as e:
            logger.error(
                f"{type(result).__name__} object has no .serialize() method: {e}"
            )
            skipped += 1
            continue

        grouped_results.setdefault(sim_id, []).append(serialized)

    if skipped:
        logger.warning(f"Skipped {skipped} results due to missing .serialize() method.")

    # Broadcast results to each simulation group layer
    for sim_id in grouped_results:
        payload = {"tool": "patient_results", "results": grouped_results[sim_id]}

        # Send event to the group layer
        logger.debug(
            f"Broadcasting {len(grouped_results[sim_id])} results to simulation_{sim_id}"
        )
        await socket_send(
            __type="simulation.metadata.results_created",
            __payload=payload,
            __status=__status,
            __simulation_id=sim_id,
        )
    return


async def broadcast_message(message: Message or int, status: str = None) -> None:
    """
    Broadcasts a message to a specific group layer using WebSocket and channels. The message
    can originate either from a system or a user. If a message ID is provided instead of a
    Message instance, the function retrieves the corresponding Message object from the database.
    Similarly, the associated Simulation object is retrieved to enrich the payload with
    additional details like sender information and simulation-specific identifiers.

    The payload generated contains relevant metadata about the message, such as the sender's
    information, display details, media attachments, and the message type. The data is then
    cleaned of null values before being broadcast to the specified group.

    :param message: Message instance or ID of the message to be broadcast.
    :type message: Message or int
    :param status: Status associated with the message being broadcast, optional.
    :type status: str, optional
    :return: None
    :rtype: None
    """
    # Get Message instance if provided ID
    if not isinstance(message, Message):
        try:
            message = await sync_to_async(Message.objects.get)(id=message)
        except Message.DoesNotExist:
            logger.error(msg=f"Message ID {message} not found. Skipping broadcast.")
            return

    # Get Simulation instance from Message FK
    try:
        simulation = await sync_to_async(Simulation.objects.get)(
            id=message.simulation_id
        )
    except Simulation.DoesNotExist:
        logger.error(
            msg=f"Simulation ID {message.simulation_id} not found. Skipping broadcast."
        )
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

    return await socket_send(
        __payload=payload, __group=group, __type="chat.message_created"
    )


async def broadcast_chat_message(message: Message or int, status: str = None):
    """Broadcasts a message to all connected clients."""
    warnings.warn(DeprecationWarning("Use `broadcast_message` instead."))

    func_name = inspect.currentframe().f_code.co_name

    async def _log(level=logging.DEBUG, msg=""):
        logger.log(level=level, msg=f"[{func_name}]: {msg}")

    # Get Message instance if provided ID
    if not isinstance(message, Message):
        try:
            message = await sync_to_async(Message.objects.get)(id=message)
        except Message.DoesNotExist:
            await _log(
                level=logging.ERROR,
                msg=f"Message ID {message} not found. Skipping broadcast.",
            )
            return

    # Get Simulation instance from Message FK
    try:
        simulation = await sync_to_async(Simulation.objects.get)(
            id=message.simulation_id
        )
    except Simulation.DoesNotExist:
        await _log(
            level=logging.ERROR,
            msg=f"Simulation ID {message.simulation_id} not found. Skipping broadcast.",
        )
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
