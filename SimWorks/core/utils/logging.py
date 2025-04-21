# core/utils/logging.py
import logging

from core.utils.hash import logger


class AppColorFormatter(logging.Formatter):
    COLORS = {
        "chatlab": "\033[94m",       # Blue
        "simai": "\033[92m",      # Green
        "accounts": "\033[95m",      # Magenta
        "notifications": "\033[93m", # Yellow
    }
    RESET = "\033[0m"

    def format(self, record):
        app = record.name.split(".")[0]
        color = self.COLORS.get(app, "")
        record.name = f"{color}{record.name}{self.RESET}" if color else record.name
        return super().format(record)


def log_model_save(instance, created: bool, model_name: str = None, extra: dict = None):
    """
    Standardized logger for model save events.

    Args:
        instance: The model instance being saved.
        created (bool): Whether this is a creation event.
        model_name (str): Optional override for the model name in logs.
        extra (dict): Optional extra fields to log for debugging.
    """
    model = model_name or instance.__class__.__name__
    prefix = f"[{model}]"
    obj_id = getattr(instance, "id", None)
    extra_data = f" | DEBUG: Full object data: {instance.__dict__}" if extra is None else f" | Extra: {extra}"

    if created:
        logger.info(f"{prefix} {instance} (ID: {obj_id}) was CREATED.{extra_data}")
    else:
        logger.info(f"{prefix} {instance} (ID: {obj_id}) was UPDATED.{extra_data}")
