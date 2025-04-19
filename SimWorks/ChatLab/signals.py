import logging
from django.db.models.signals import post_save
from django.apps import apps

logger = logging.getLogger(__name__)

def log_model_save(sender, instance, created, **kwargs):
    class_name = sender.__name__
    object_id = getattr(instance, 'id', 'N/A')
    object_name = str(instance)

    status = "CREATED" if created else "MODIFIED"
    msg = f"[{class_name}] {object_name} (ID: {object_id}) was {status}."

    if logger.isEnabledFor(logging.DEBUG):
        try:
            debug_info = f"Full object data: {vars(instance)}"
        except Exception as e:
            debug_info = f"(Could not inspect instance: {e})"
        msg += f" | DEBUG: {debug_info}"

    logger.info(msg)

# Connect only once per model
for model in apps.get_app_config("ChatLab").get_models():
    post_save.connect(
        log_model_save,
        sender=model,
        dispatch_uid=f"chatlab_log_save_{model.__name__}"
    )