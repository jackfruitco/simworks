from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils.timezone import now

from apps.accounts.models import UserRole
from apps.simcore.models import Simulation
from apps.simcore.services import is_simulation_billable

User = get_user_model()


def _make_user(email="test@example.com"):
    role, _ = UserRole.objects.get_or_create(title="Tester")
    return User.objects.create_user(email=email, password="pw", role=role)


def _make_simulation(user=None, status=Simulation.SimulationStatus.IN_PROGRESS):
    sim = Simulation.objects.create(user=user, status=status)
    return sim


class SimulationArchiveMethodTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.sim = _make_simulation(user=self.user)

    def test_is_archived_false_when_archived_at_is_null(self):
        self.assertFalse(self.sim.is_archived)

    def test_is_archived_true_after_archive(self):
        self.sim.archive(reason=Simulation.ArchiveReason.SYSTEM_FAILED)
        self.assertTrue(self.sim.is_archived)

    def test_archive_sets_all_fields(self):
        ts = now()
        self.sim.archive(
            reason=Simulation.ArchiveReason.USER_ARCHIVED,
            archived_by=self.user,
            timestamp=ts,
        )
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.archived_at, ts)
        self.assertEqual(self.sim.archived_reason, Simulation.ArchiveReason.USER_ARCHIVED)
        self.assertEqual(self.sim.archived_by, self.user)

    def test_archive_is_idempotent(self):
        first_ts = now() - timedelta(seconds=10)
        self.sim.archive(reason=Simulation.ArchiveReason.SYSTEM_FAILED, timestamp=first_ts)
        self.sim.refresh_from_db()
        # Second call with different timestamp should be a no-op
        second_ts = now()
        self.sim.archive(reason=Simulation.ArchiveReason.USER_ARCHIVED, timestamp=second_ts)
        self.sim.refresh_from_db()
        self.assertEqual(self.sim.archived_at, first_ts)
        self.assertEqual(self.sim.archived_reason, Simulation.ArchiveReason.SYSTEM_FAILED)

    def test_unarchive_clears_fields(self):
        self.sim.archive(reason=Simulation.ArchiveReason.STAFF_ARCHIVED, archived_by=self.user)
        self.sim.unarchive()
        self.sim.refresh_from_db()
        self.assertIsNone(self.sim.archived_at)
        self.assertEqual(self.sim.archived_reason, "")
        self.assertIsNone(self.sim.archived_by)

    def test_archive_without_save_does_not_persist(self):
        self.sim.archive(reason=Simulation.ArchiveReason.SYSTEM_FAILED, save=False)
        # In-memory change applied
        self.assertTrue(self.sim.is_archived)
        # But not persisted
        fresh = Simulation.objects.get(pk=self.sim.pk)
        self.assertFalse(fresh.is_archived)

    def test_unarchive_without_save_does_not_persist(self):
        self.sim.archive(reason=Simulation.ArchiveReason.SYSTEM_FAILED)
        self.sim.unarchive(save=False)
        self.assertIsNone(self.sim.archived_at)
        fresh = Simulation.objects.get(pk=self.sim.pk)
        self.assertIsNotNone(fresh.archived_at)


class IsSimulationBillableTests(TestCase):
    def test_in_progress_simulation_is_billable(self):
        sim = _make_simulation(status=Simulation.SimulationStatus.IN_PROGRESS)
        self.assertTrue(is_simulation_billable(sim))

    def test_completed_simulation_is_billable(self):
        sim = _make_simulation(status=Simulation.SimulationStatus.COMPLETED)
        self.assertTrue(is_simulation_billable(sim))

    def test_timed_out_simulation_is_billable(self):
        sim = _make_simulation(status=Simulation.SimulationStatus.TIMED_OUT)
        self.assertTrue(is_simulation_billable(sim))

    def test_canceled_simulation_is_billable(self):
        sim = _make_simulation(status=Simulation.SimulationStatus.CANCELED)
        self.assertTrue(is_simulation_billable(sim))

    def test_failed_simulation_is_not_billable(self):
        sim = _make_simulation(status=Simulation.SimulationStatus.FAILED)
        self.assertFalse(is_simulation_billable(sim))
