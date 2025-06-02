# simai/tasks.py
import asyncio
import logging
import warnings

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from chatlab.utils import broadcast_chat_message, broadcast_message, broadcast_patient_results
from simai.client import SimAIClient
from simcore.models import Simulation, LabResult, RadResult

logger = logging.getLogger(__name__)

@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_reply_image_task(simulation_id):
    """
    Celery task to asynchronously generate a patient reply image for a given simulation.

    This task retrieves the simulation object, initializes the SimAIClient,
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
        service = SimAIClient()
        messages = await service.generate_patient_reply_image(simulation=simulation)
        for message in messages:
            await broadcast_message(message)
        return messages

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

@shared_task(time_limit=120, soft_time_limit=110)
def generate_patient_results(
        __simulation_id: int,
        __lab_orders: str | list[str] = None,
        __rad_orders: str | list[str] = None,
) -> None:
    """
    Celery task to asynchronously generate patient results for a given simulation.

    This task retrieves the simulation object, initializes the SimAIClient,
    and uses it to generate lab and/or radiology results.

    Args:
        __simulation_id: ID of the Simulation object.
        __lab_orders: Optional list or comma-separated string of lab orders.
        __rad_orders: Optional list or comma-separated string of radiology orders.
    """
    try:
        simulation = Simulation.objects.get(pk=__simulation_id)
    except Simulation.DoesNotExist as e:
        logger.warning(f"Simulation ID {__simulation_id} not found. Skipping patient result(s) generation.")
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve simulation (provided {type(__simulation_id)} `{__simulation_id}`: {e}")
        raise

    # Normalize input if needed
    if isinstance(__lab_orders, str):
        __lab_orders = [o.strip() for o in __lab_orders.split(",")]

    if isinstance(__rad_orders, str):
        __rad_orders = [o.strip() for o in __rad_orders.split(",")]

    async def run():
        service = SimAIClient()
        results = await service.generate_patient_results(
            simulation=simulation,
            lab_orders=__lab_orders,
            rad_orders=__rad_orders
        )
        logger.debug(f"[generate_patient_results] Generated results: {results}")

        try:
            await broadcast_patient_results(results)
        except Exception as e:
            logger.error(f"[generate_patient_results] Failed to broadcast: {e}")
        return results

    try:
        asyncio.run(run())
    except SoftTimeLimitExceeded:
        logger.warning(f"[generate_patient_results] Soft time limit exceeded for Sim {__simulation_id}")
    except Exception as e:
        logger.error(f"[generate_patient_results] Task failed: {e}")
        raise