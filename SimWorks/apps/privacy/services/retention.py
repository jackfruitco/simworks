from datetime import timedelta

from django.utils import timezone

from apps.chatlab.models import Message
from apps.privacy import policies
from orchestrai_django.models import ServiceCall, ServiceCallAttempt


class RetentionService:
    @classmethod
    def purge_expired_chat_messages(cls) -> int:
        cutoff = timezone.now() - timedelta(days=policies.chat_retention_days())
        deleted, _ = Message.objects.filter(timestamp__lt=cutoff).delete()
        return deleted

    @classmethod
    def purge_expired_raw_ai_payloads(cls) -> dict:
        cutoff = timezone.now() - timedelta(days=policies.raw_ai_retention_days())
        call_count = ServiceCall.objects.filter(created_at__lt=cutoff).update(
            request=None,
            messages_json=[],
        )
        attempt_count = ServiceCallAttempt.objects.filter(created_at__lt=cutoff).update(
            request_input=None,
            request_pydantic=None,
            request_provider=None,
            request_messages=[],
            request_tools=None,
            response_raw=None,
            response_provider_raw=None,
            agent_config=None,
        )
        return {"service_calls": call_count, "service_call_attempts": attempt_count}
