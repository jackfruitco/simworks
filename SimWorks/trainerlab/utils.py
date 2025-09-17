# trainerlab/utils.py
import logging

from django.apps import apps
from django.contrib.auth import get_user_model

from simcore.models import Simulation
from simcore.utils import generate_fake_name
from trainerlab.models import TrainerSession

User = get_user_model()

logger = logging.getLogger(__name__)

APP_CONFIG = apps.get_app_config(app_label="trainerlab")

async def create_new_simulation(
        user: User | int,
        modifiers: list = None,
        force: bool = False,
        request_session: bool = False,
) -> Simulation | TrainerSession:
    """Create a new Simulation and TrainerSession, and trigger a celery task."""
    sim_patient_full_name = await generate_fake_name()

    if isinstance(user, int):
        user = await User.objects.aget(id=user)

    # Create base Simulation
    simulation = await Simulation.abuild(
        user=user,
        lab=APP_CONFIG.name,
        sim_patient_full_name=sim_patient_full_name,
        modifiers=modifiers,
    )

    # Link ChatLab extension
    session = await TrainerSession.objects.acreate(simulation=simulation)

    # Generate an initial message
    # logger.debug(
    #     f"Starting celery task to generate initial data for Sim#{simulation.id}"
    # )
    # from simai.tasks import generate_patient_initial as task
    # task.delay(simulation.id, force)

    return simulation if not request_session else session