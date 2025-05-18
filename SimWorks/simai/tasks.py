# simai/tasks.py
import asyncio
import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from simai.async_client import AsyncOpenAIService
from simcore.models import Simulation

logger = logging.getLogger(__name__)

@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_reply_image_task(simulation_id):
    """
    Celery task to asynchronously generate a patient reply image for a given simulation.

    This task retrieves the simulation object, initializes the AsyncOpenAIService,
    and uses it to generate an image representation of the patient associated
    with the simulation.

    Args:
        simulation_id: The primary key (ID) of the Simulation object for which
                      to generate the patient image.

    Returns:
        None: The task processes the image generation asynchronously and stores
              the result in the database through the service method.
    """
    try:
        simulation = Simulation.objects.get(pk=simulation_id)
    except Simulation.DoesNotExist:
        logger.warning(f"Simulation ID {simulation_id} not found. Skipping image generation.")
        return f"Simulation {simulation_id} not found (404)"

    async def run():
        service = AsyncOpenAIService()
        await service.generate_patient_reply_image(simulation=simulation)

    try:
        asyncio.run(run())
        return None
    except SoftTimeLimitExceeded:
        logger.warning(f"[generate_patient_reply_image_task] Soft time limit exceeded for Sim {simulation_id}")
        return f"Soft time limit exceeded for Sim {simulation_id}"
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Image generation failed: {e}")
        raise