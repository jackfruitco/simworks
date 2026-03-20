from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.chatlab.models import Message, RoleChoices
from apps.privacy.services.classification import scan_text_for_pii
from apps.privacy.services.retention import RetentionService
from apps.simcore.models import Conversation, ConversationType, Simulation, SimulationSummary
from orchestrai_django.models import ServiceCall, ServiceCallAttempt


class PrivacyTests(TestCase):
    def setUp(self):
        self.role = UserRole.objects.create(title="Student")
        self.user = User.objects.create_user(
            email="student@example.com",
            password="password123",
            first_name="Test",
            last_name="User",
            role=self.role,
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.sim = Simulation.objects.create(user=self.user)
        self.conv_type = ConversationType.objects.create(
            slug="simulated_patient_test",
            display_name="Patient",
        )
        self.conversation = Conversation.objects.create(
            simulation=self.sim,
            conversation_type=self.conv_type,
        )

    def test_privacy_defaults_minimize_raw_persistence(self):
        from django.conf import settings

        self.assertFalse(settings.PRIVACY_PERSIST_RAW_AI_REQUESTS)
        self.assertFalse(settings.PRIVACY_PERSIST_RAW_AI_RESPONSES)
        self.assertFalse(settings.PRIVACY_PERSIST_PROVIDER_RAW)

    def test_export_endpoint_includes_summary(self):
        SimulationSummary.objects.create(
            simulation=self.sim,
            summary_text="Strong diagnostic approach",
            chief_complaint="Chest pain",
            diagnosis="GERD",
            strengths=["History-taking"],
            improvement_areas=["Differential breadth"],
            learning_points=["Risk stratification"],
            recommended_study_topics=["ACS workup"],
        )
        response = self.client.get(reverse("privacy:export"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["simulation_summaries"])
        self.assertNotIn("password", str(payload))

    def test_delete_account_removes_service_calls(self):
        call = ServiceCall.objects.create(
            service_identity="chatlab.patient",
            related_object_id=str(self.sim.id),
        )
        ServiceCallAttempt.objects.create(service_call=call, attempt=1)
        response = self.client.post(reverse("privacy:delete_account"), {"confirmation": "DELETE"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(id=self.user.id).exists())
        self.assertFalse(ServiceCall.objects.filter(id=call.id).exists())
        self.assertFalse(ServiceCallAttempt.objects.filter(service_call_id=call.id).exists())

    @override_settings(PRIVACY_CHAT_RETENTION_DAYS=1, PRIVACY_RAW_AI_RETENTION_DAYS=1)
    def test_retention_cleanup_removes_expired_raw_data(self):
        msg = Message.objects.create(
            simulation=self.sim,
            conversation=self.conversation,
            sender=self.user,
            role=RoleChoices.USER,
            content="old",
        )
        Message.objects.filter(id=msg.id).update(timestamp=timezone.now() - timedelta(days=5))
        call = ServiceCall.objects.create(
            service_identity="chatlab.patient",
            related_object_id=str(self.sim.id),
            request={"raw": "request"},
            messages_json=[{"content": "raw"}],
        )
        attempt = ServiceCallAttempt.objects.create(
            service_call=call,
            attempt=1,
            request_input={"raw": True},
            response_raw={"raw": True},
            response_provider_raw={"raw": True},
        )
        ServiceCall.objects.filter(id=call.id).update(created_at=timezone.now() - timedelta(days=5))
        ServiceCallAttempt.objects.filter(id=attempt.id).update(created_at=timezone.now() - timedelta(days=5))

        RetentionService.purge_expired_chat_messages()
        RetentionService.purge_expired_raw_ai_payloads()

        self.assertFalse(Message.objects.filter(id=msg.id).exists())
        call.refresh_from_db()
        attempt.refresh_from_db()
        self.assertIsNone(call.request)
        self.assertEqual(call.messages_json, [])
        self.assertIsNone(attempt.request_input)
        self.assertIsNone(attempt.response_raw)

    def test_pii_scan_detects_basic_patterns(self):
        result = scan_text_for_pii("email me at a@b.com and ssn 123-45-6789")
        self.assertTrue(result["has_pii"])
        self.assertTrue(result["matches"]["email"])
        self.assertTrue(result["matches"]["ssn"])

    @override_settings(PRIVACY_ANALYTICS_ENABLED=True, PRIVACY_ANALYTICS_REQUIRE_CONSENT=True)
    def test_analytics_is_consent_gated(self):
        from apps.privacy.analytics import PrivacyAnalytics

        self.assertFalse(
            PrivacyAnalytics.emit(
                event_name="simulation.completed",
                subject_id="u_1",
                properties={"message": "secret", "duration_ms": 2000},
                consented=False,
            )
        )
        self.assertTrue(
            PrivacyAnalytics.emit(
                event_name="simulation.completed",
                subject_id="u_1",
                properties={"duration_ms": 2000},
                consented=True,
            )
        )

    def test_chat_input_warning_renders(self):
        response = self.client.get(reverse("chatlab:run_simulation", kwargs={"simulation_id": self.sim.id}))
        self.assertContains(response, "Privacy reminder")

    @override_settings(PRIVACY_CHAT_RETENTION_DAYS=1)
    def test_summary_survives_message_purge(self):
        SimulationSummary.objects.create(simulation=self.sim, summary_text="durable")
        msg = Message.objects.create(
            simulation=self.sim,
            conversation=self.conversation,
            sender=self.user,
            role=RoleChoices.USER,
            content="old",
        )
        Message.objects.filter(id=msg.id).update(timestamp=timezone.now() - timedelta(days=5))
        RetentionService.purge_expired_chat_messages()
        self.assertTrue(SimulationSummary.objects.filter(simulation=self.sim).exists())
