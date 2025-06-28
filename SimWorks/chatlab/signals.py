import logging

from core.utils import log_model_save
from django.apps import apps
from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


def log_model_save_signal(sender, instance, created, **kwargs):
    log_model_save(instance, created)


# Connect only once per model
for model in apps.get_app_config("chatlab").get_models():
    post_save.connect(
        log_model_save_signal,
        sender=model,
        dispatch_uid=f"chatlab_log_save_{model.__name__}",
    )
