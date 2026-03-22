from pathlib import Path

from django.test import SimpleTestCase, TestCase

from apps.common.models import OutboxEvent
from apps.common.outbox import event_types
from apps.common.outbox.outbox import enqueue_event_sync, order_outbox_queryset


class EventTypeRegistryTests(SimpleTestCase):
    def test_all_canonical_event_types_follow_strict_contract(self) -> None:
        for event_type in event_types.canonical_event_types():
            with self.subTest(event_type=event_type):
                self.assertTrue(event_types.is_valid_canonical_event_type(event_type))
                self.assertEqual(event_type, event_types.canonical_event_type(event_type))
                self.assertTrue(event_types.is_known_event_type(event_type, allow_aliases=False))
                self.assertEqual(event_type.count("."), 2)
                self.assertNotIn("_", event_type)

                domain, subject, action = event_type.split(".")
                self.assertIn(domain, event_types.CANONICAL_DOMAINS)
                self.assertTrue(subject.islower())
                self.assertTrue(subject.isalpha())
                self.assertIn(action, event_types.CANONICAL_ACTIONS)

    def test_legacy_aliases_canonicalize_to_registry_names(self) -> None:
        expected_aliases = {
            "chat.message_created": event_types.MESSAGE_CREATED,
            "message_status_update": event_types.MESSAGE_DELIVERY_UPDATED,
            "simulation.state_changed": event_types.SIMULATION_STATUS_UPDATED,
            "run.started": event_types.SIMULATION_STATUS_UPDATED,
            "session.failed": event_types.SIMULATION_STATUS_UPDATED,
            "feedback.retrying": event_types.FEEDBACK_GENERATION_UPDATED,
            "trainerlab.intervention.assessed": event_types.PATIENT_INTERVENTION_UPDATED,
            "trainerlab.control_plane.patch_evaluated": (
                event_types.SIMULATION_PATCH_EVALUATION_COMPLETED
            ),
            "patient.recommended_intervention.created": (
                event_types.PATIENT_RECOMMENDED_INTERVENTION_CREATED
            ),
        }

        for legacy_name, canonical_name in expected_aliases.items():
            with self.subTest(legacy_name=legacy_name):
                self.assertTrue(event_types.is_known_event_type(legacy_name))
                self.assertNotEqual(legacy_name, canonical_name)
                self.assertEqual(event_types.canonical_event_type(legacy_name), canonical_name)

    def test_docs_and_typings_cover_all_canonical_event_types(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        docs_text = (repo_root / "docs" / "WEBSOCKET_EVENTS.md").read_text()
        typings_text = (
            repo_root
            / "SimWorks"
            / "apps"
            / "common"
            / "static"
            / "common"
            / "js"
            / "simulation-events.d.ts"
        ).read_text()

        for event_type in event_types.canonical_event_types():
            with self.subTest(event_type=event_type):
                self.assertIn(event_type, docs_text)
                self.assertIn(event_type, typings_text)


class OutboxEventContractTests(TestCase):
    def test_enqueue_event_sync_canonicalizes_legacy_aliases(self) -> None:
        event = enqueue_event_sync(
            event_type="chat.message_created",
            simulation_id=101,
            payload={"message_id": 7},
            idempotency_key="legacy-alias-message-created",
            correlation_id="corr-1",
        )

        assert event is not None
        self.assertEqual(event.event_type, event_types.MESSAGE_CREATED)
        self.assertEqual(
            OutboxEvent.objects.get(id=event.id).event_type,
            event_types.MESSAGE_CREATED,
        )

    def test_enqueue_event_sync_rejects_noncanonical_output(self) -> None:
        with self.assertRaisesMessage(ValueError, "Invalid canonical outbox event type"):
            enqueue_event_sync(
                event_type="simulation.status.ready",
                simulation_id=101,
                payload={"status": "ready"},
                idempotency_key="invalid-canonical-name",
            )

    def test_prefix_filters_match_canonical_domains_and_subjects(self) -> None:
        created_types = (
            event_types.MESSAGE_DELIVERY_UPDATED,
            event_types.PATIENT_PROBLEM_UPDATED,
            event_types.SIMULATION_STATUS_UPDATED,
            event_types.PATIENT_RESOURCE_UPDATED,
        )
        for index, event_type in enumerate(created_types, start=1):
            enqueue_event_sync(
                event_type=event_type,
                simulation_id=999,
                payload={"index": index},
                idempotency_key=f"{event_type}:{index}",
            )

        def _types_for(prefix: str) -> list[str]:
            queryset = order_outbox_queryset(
                OutboxEvent.objects.filter(
                    simulation_id=999,
                    event_type__startswith=prefix,
                )
            )
            return list(queryset.values_list("event_type", flat=True))

        self.assertEqual(_types_for("simulation."), [event_types.SIMULATION_STATUS_UPDATED])
        self.assertEqual(
            _types_for("patient."),
            [event_types.PATIENT_PROBLEM_UPDATED, event_types.PATIENT_RESOURCE_UPDATED],
        )
        self.assertEqual(_types_for("patient.problem."), [event_types.PATIENT_PROBLEM_UPDATED])
        self.assertEqual(
            _types_for("message.delivery."),
            [event_types.MESSAGE_DELIVERY_UPDATED],
        )
