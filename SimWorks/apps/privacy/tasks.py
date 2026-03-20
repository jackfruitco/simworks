from django.tasks import task

from .services.retention import RetentionService


@task
def run_privacy_retention_cleanup() -> dict:
    return {
        "messages_deleted": RetentionService.purge_expired_chat_messages(),
        **RetentionService.purge_expired_raw_ai_payloads(),
    }
