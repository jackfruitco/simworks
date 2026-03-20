from __future__ import annotations

from dataclasses import dataclass

from . import policies


@dataclass(frozen=True)
class PrivacyAnalyticsEvent:
    event_name: str
    subject_id: str
    properties: dict


class PrivacyAnalytics:
    """Privacy-safe analytics facade.

    Constraints:
    - no raw chat content
    - no raw AI payloads
    - no direct email/name identifiers
    """

    forbidden_keys = {"email", "name", "full_name", "message", "content", "payload"}

    @classmethod
    def build_event(cls, *, event_name: str, subject_id: str, properties: dict) -> PrivacyAnalyticsEvent:
        cleaned = {k: v for k, v in properties.items() if k not in cls.forbidden_keys}
        return PrivacyAnalyticsEvent(event_name=event_name, subject_id=subject_id, properties=cleaned)

    @classmethod
    def emit(cls, *, event_name: str, subject_id: str, properties: dict, consented: bool) -> bool:
        if not policies.analytics_enabled():
            return False
        if policies.analytics_require_consent() and not consented:
            return False
        cls.build_event(event_name=event_name, subject_id=subject_id, properties=properties)
        return True
