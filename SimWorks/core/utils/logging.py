# core/utils/logging.py
import logging

class AppColorFormatter(logging.Formatter):
    COLORS = {
        "chatlab": "\033[94m",          # Blue
        "simai": "\033[92m",            # Green
        "accounts": "\033[95m",         # Magenta
        "notifications": "\033[93m",    # Yellow
        "simcore": "\033[96m",          # Cyan
        "core": "\033[90m",             # Gray
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

    # Determine app-level logger
    app_label = instance._meta.app_label
    model_logger = logging.getLogger(app_label)

    # Only show full debug info if app-level logger is set to DEBUG
    if model_logger.isEnabledFor(logging.DEBUG):
        extra_data = f" | DEBUG: Full object data: {instance.__dict__}" if extra is None else f" | Extra: {extra}"
    else:
        extra_data = ""

    msg = f"{prefix} {instance} (ID: {obj_id}) was {'CREATED' if created else 'UPDATED'}.{extra_data}"
    model_logger.info(msg)
