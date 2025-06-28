# simcore/history_registry.py
import csv
import io
import json

from core.utils import Formatter

_registry = {}


def register_history_provider(app_label, func):
    """
    Register a history retrieval function for a specific app.
    Each function must accept a Simulation and return a list of history records (dicts).
    """
    _registry[app_label] = func


def get_sim_history(simulation, format: str = None):
    """
    Returns a combined list of history records from all registered apps for a given simulation.
    If a format is provided, returns a formatted representation using core.utils.Formatter.
    """
    history = []
    for app_label, func in _registry.items():
        try:
            history.extend(func(simulation))
        except Exception as e:
            from django.conf import settings

            if settings.DEBUG:
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(f"[get_sim_history] Failed for {app_label}: {e}")

    if format is None:
        return history

    return Formatter(history).render(format)
