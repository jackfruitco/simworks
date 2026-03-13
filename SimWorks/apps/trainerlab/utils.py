# trainerlab/utils.py
import logging

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from apps.simcore.models import Simulation
from apps.trainerlab.models import TrainerSession
from apps.trainerlab.services import create_session_with_initial_generation

User = get_user_model()
logger = logging.getLogger(__name__)


async def create_new_simulation(
    user: User | int,
    modifiers: list | None = None,
    force: bool = False,
    request_session: bool = False,
) -> Simulation | TrainerSession:
    """Create a new Simulation and TrainerSession, and trigger a celery task."""
    if isinstance(user, int):
        user = await User.objects.aget(id=user)

    session, call_id = await sync_to_async(create_session_with_initial_generation)(
        user=user,
        scenario_spec={},
        directives=None,
        modifiers=modifiers,
    )

    if call_id is None:
        logger.warning("Initial generation enqueue failed for simulation %s", session.simulation_id)

    return session if request_session else session.simulation
