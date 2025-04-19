import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.apps import apps

logger = logging.getLogger(__name__)

# Cache ChatLab models to restrict logging only to this app
chatlab_models = set(apps.get_app_config("ChatLab").get_models())

@receiver(post_save)
def log_model_save(sender, instance, created, **kwargs):
    # Skip if sender is not a model from this app
    if sender not in chatlab_models:
        return

    class_name = sender.__name__
    object_id = getattr(instance, "id", "N/A")
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

# Connect post_save for each model in ChatLab
for model in chatlab_models:
    post_save.connect(log_model_save, sender=model, dispatch_uid=f"log_save_ChatLab_{model.__name__}")