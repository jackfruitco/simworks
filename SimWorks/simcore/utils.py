# simcore/utils.py
import logging
import random
from typing import TYPE_CHECKING, Union

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from faker import Faker

if TYPE_CHECKING:
    from simcore.models import Simulation

fake = Faker()

@sync_to_async
def generate_fake_name() -> str:
    return fake.name()

def randomize_display_name(full_name: str) -> str:
    parts = full_name.strip().split()
    if len(parts) < 2:
        return full_name  # fallback

    first, last = parts[0], parts[1]
    initials = f"{first[0]}{last[0]}"
    options = [
        full_name,
        f"{first} {last}",
        f"{first[0]}. {last}",
        f"{first} {last[0]}.",
        f"{first.lower()} {last.lower()}",
        f"{first.lower()} {last[0].lower()}",
        f"{initials}",
        f"{initials.upper()}",
        f"{first.capitalize()} {last[0].upper()}.",
        f"{first[0].upper()}.{last[0].upper()}.",
    ]
    return random.choice(options)


def get_user_initials(user) -> str:
    """
    Returns initials for a User object.
    - If first_name and last_name are set: returns first letters of each
    - If only username is set: returns first letter
    - If username is numeric: returns 'Unk'
    """

    User = get_user_model()
    if type(user) == str:
        try:
            user = User.objects.get(username=user)
        except User.DoesNotExist:
            raise Exception(f"Error! get_user_initials: Username {user} not found")

    if (
        hasattr(user, "first_name")
        and hasattr(user, "last_name")
        and user.first_name
        and user.last_name
    ):
        return f"{user.first_name[0]}{user.last_name[0]}".upper()
    elif hasattr(user, "username") and user.username and not user.username.isnumeric():
        return user.username[0].upper()
    return "Unk"

def resolve_simulation(__target: Union[int, str, "Simulation"], __logger=None) -> "Simulation":
    from simcore.models import Simulation
    ...
    """
    Resolves a simulation instance by its ID. This function attempts to fetch
    a simulation object from the database using the provided ID. If a logger
    object is not provided, it initializes a default logger. Upon successful
    retrieval, it returns the simulation instance. If the simulation with the
    given ID does not exist, an exception is raised.

    :param __target: The ID of the simulation to resolve. Can be an integer or a string.
    :param __logger: Optional. Logger instance that will log the debug messages. If
        not provided, a default logger will be used.
    :return: The resolved simulation instance.

    :raises ObjectDoesNotExist: If the simulation with the specified ID does not exist.
    """
    from simcore.models import Simulation
    logger = __logger or logging.getLogger(__name__)

    if isinstance(__target, Simulation):
        logger.debug(f"[resolve_simulation] Provided already resolved simulation {__target.id}")
        return __target
    else:
        __target = int(__target)
    try:
        instance = Simulation.objects.get(id=__target)
        logger.debug(f"[resolve_simulation] Resolved simulation {instance.id}")
        return instance
    except Simulation.DoesNotExist as e:
        raise ObjectDoesNotExist(f"Simulation with ID {__target} not found.") from e

async def aresolve_simulation(__target: Union[int, str, "Simulation"], __logger=None) -> "Simulation":
    """
    Resolves and retrieves a `Simulation` instance asynchronously by its ID.
    The function logs the resolution process for debugging purposes and raises
    an exception if the simulation instance is not found.

    :param __target: ID of the simulation instance to resolve. Can be an integer or string.
    :type __target: int | str
    :param __logger: Optional logger instance for logging the resolution process. If not provided,
        a default logger is used.
    :type __logger: logging.Logger, optional
    :return: The resolved `Simulation` instance.
    :rtype: Simulation
    :raises ObjectDoesNotExist: If no `Simulation` instance is found with the given ID.
    """
    from simcore.models import Simulation
    logger = __logger or logging.getLogger(__name__)

    if isinstance(__target, Simulation):
        logger.debug(f"[resolve_simulation] Provided already resolved simulation {__target.id}")
        return __target
    else:
        __target = int(__target)

    try:
        instance = await Simulation.objects.aget(id=__target)
        logger.debug(f"[resolve_simulation] Resolved simulation {instance.id}")
        return instance
    except Simulation.DoesNotExist as e:
        raise ObjectDoesNotExist(f"Simulation with ID {__target} not found.") from e
