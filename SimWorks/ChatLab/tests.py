from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import get_default_prompt
from .models import Message
from .models import Prompt
from .models import RoleChoices
from .models import Simulation

User = get_user_model()


class PromptModelTests(TestCase):
    def test_prompt_creation_and_str(self):
        user = User.objects.create_user(username="tester")
        prompt = Prompt.objects.create(
            created_by=user,
            title="Scenario A",
            content="Simulate a casualty in the field",
        )
        self.assertEqual(str(prompt), "Scenario A")
        self.assertTrue(prompt.is_active)
        prompt.is_archived = True
        self.assertFalse(prompt.is_active)

    def test_get_default_prompt(self):
        default_id = get_default_prompt()
        prompt = Prompt.objects.get(id=default_id)
        self.assertEqual(prompt.title, "Default Prompt")

    def test_prompt_modified_fields_on_update(self):
        user = User.objects.create_user(username="creator")
        editor = User.objects.create_user(username="editor")
        prompt = Prompt.objects.create(
            created_by=user, title="Initial Prompt", content="Initial content"
        )

        self.assertIsNone(prompt.modified_by)
        self.assertIsNone(prompt.modified_at)

        prompt.content = "Updated content"
        prompt.set_modified_by(editor)
        prompt.save()

        prompt.refresh_from_db()
        self.assertEqual(prompt.modified_by, editor)
        self.assertIsNotNone(prompt.modified_at)

    def test_prompt_created_by_can_be_null(self):
        prompt = Prompt.objects.create(
            title="System Generated",
            content="System-created default prompt.",
            created_by=None,
        )
        self.assertIsNone(prompt.created_by)
        self.assertEqual(str(prompt), "System Generated")

    def test_prompt_modified_by_not_set_without_helper(self):
        user = User.objects.create_user(username="owner")
        prompt = Prompt.objects.create(
            title="Prompt Without Helper", content="Testing default", created_by=user
        )
        prompt.content = "Updated again"
        prompt.save()
        prompt.refresh_from_db()
        self.assertIsNone(prompt.modified_by)


class SimulationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sim_user")
        self.sim_patient_name = "Tyler Johnson"

    def test_simulation_str_and_props(self):
        sim = Simulation.objects.create(user=self.user)
        self.assertIn("ChatLab Sim #", str(sim))
        self.assertTrue(sim.in_progress)
        self.assertFalse(sim.is_complete)
        self.assertFalse(sim.is_timed_out)
        sim.end = timezone.now()
        sim.save()
        self.assertTrue(sim.is_complete)

    def test_simulation_with_time_limit(self):
        sim = Simulation.objects.create(user=self.user, time_limit=timedelta(seconds=1))
        sim.start = timezone.now() - timedelta(seconds=2)
        sim.save()
        self.assertTrue(sim.is_timed_out)
        self.assertTrue(sim.is_complete)

    def test_simulation_length_property(self):
        now = timezone.now()
        sim = Simulation.objects.create(
            user=self.user, start=now, end=now + timedelta(minutes=10)
        )
        self.assertEqual(sim.length, timedelta(minutes=10))

    def test_simulation_history(self):
        sim = Simulation.objects.create(user=self.user)
        Message.objects.create(
            simulation=sim, sender=self.user, content="Hello", role=RoleChoices.USER
        )
        Message.objects.create(
            simulation=sim,
            sender=self.user,
            content="Respond",
            role=RoleChoices.ASSISTANT,
        )
        history = sim.history
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], RoleChoices.ASSISTANT)

    def test_simulation_uses_default_prompt(self):
        sim = Simulation.objects.create(user=self.user)
        self.assertIsNotNone(sim.prompt)
        self.assertEqual(sim.prompt.title, "Default Prompt")

    def test_simulation_history_ordering(self):
        sim = Simulation.objects.create(user=self.user)
        Message.objects.create(
            simulation=sim, sender=self.user, content="Oldest", role=RoleChoices.USER
        )
        Message.objects.create(
            simulation=sim,
            sender=self.user,
            content="Newest",
            role=RoleChoices.ASSISTANT,
        )
        history = sim.history
        self.assertEqual(history[0]["content"], "Newest")

    def test_simulation_queryset_filter_by_user(self):
        other = User.objects.create_user(username="someone_else")
        Simulation.objects.create(user=self.user)
        Simulation.objects.create(user=other)
        user_sims = Simulation.objects.filter(user=self.user)
        self.assertEqual(user_sims.count(), 1)

    def test_simulation_prompt_is_default_if_not_set(self):
        sim = Simulation.objects.create(user=self.user)
        self.assertEqual(sim.prompt.title, "Default Prompt")

    def test_message_order_in_simulation(self):
        sim = Simulation.objects.create(user=self.user)
        m1 = Message.objects.create(simulation=sim, sender=self.user, content="first")
        m2 = Message.objects.create(simulation=sim, sender=self.user, content="second")
        all_messages = sim.message_set.order_by("order")
        self.assertEqual(list(all_messages), [m1, m2])

    def test_message_deletion_on_simulation_delete(self):
        sim = Simulation.objects.create(user=self.user)
        Message.objects.create(simulation=sim, sender=self.user, content="bye")
        sim.delete()
        self.assertEqual(Message.objects.count(), 0)

    def test_invalid_role_rejected(self):
        with self.assertRaises(ValueError):
            Message.objects.create(
                simulation=self.sim, sender=self.user, content="Invalid", role="doctor"
            )

    def test_message_with_response_link(self):
        sim = Simulation.objects.create(user=self.user)
        response = Message.objects.create(
            simulation=sim,
            sender=self.user,
            content="response",
            role=RoleChoices.ASSISTANT,
        )
        msg = Message.objects.create(
            simulation=sim,
            sender=self.user,
            content="prompt",
            role=RoleChoices.USER,
            openai_response=response,
        )
        self.assertEqual(msg.openai_response, response)

    def test_message_str_defaults(self):
        msg = Message.objects.create(
            simulation=self.sim, sender=self.user, content="Just testing"
        )
        self.assertIn("Just testing", str(msg))

    def test_sim_patient_display_name_only_changes_if_full_name_changes(self):
        sim = Simulation.objects.create(
            user=self.user, sim_patient_full_name="Tyler Johnson"
        )
        original_display = sim.sim_patient_display_name

        # Save again without changing full name — display name should not change
        sim.save()
        sim.refresh_from_db()
        self.assertEqual(sim.sim_patient_display_name, original_display)

        # Change full name — display name should change
        sim.sim_patient_full_name = "James Tyler"
        sim.save()
        sim.refresh_from_db()
        self.assertNotEqual(sim.sim_patient_display_name, original_display)


class MessageModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="msg_user")
        self.sim = Simulation.objects.create(user=self.user)

    def test_message_ordering_and_str(self):
        m1 = Message.objects.create(
            simulation=self.sim, sender=self.user, content="First"
        )
        m2 = Message.objects.create(
            simulation=self.sim, sender=self.user, content="Second"
        )
        self.assertEqual(m1.order, 1)
        self.assertEqual(m2.order, 2)

    def test_get_previous_openai_id(self):
        m1 = Message.objects.create(
            simulation=self.sim,
            sender=self.user,
            content="Bot reply",
            role=RoleChoices.ASSISTANT,
            openai_id="abc123",
        )
        m2 = Message.objects.create(
            simulation=self.sim,
            sender=self.user,
            content="User msg",
            role=RoleChoices.USER,
        )
        m3 = Message.objects.create(
            simulation=self.sim,
            sender=self.user,
            content="Bot again",
            role=RoleChoices.ASSISTANT,
        )
        self.assertEqual(m3.get_previous_openai_id(), "abc123")

    def test_get_openai_input(self):
        msg = Message.objects.create(
            simulation=self.sim, sender=self.user, content="Hi"
        )
        expected = [{"role": RoleChoices.USER, "content": "Hi"}]
        self.assertEqual(msg.get_openai_input(), expected)

    def test_set_openai_id(self):
        msg = Message.objects.create(
            simulation=self.sim, sender=self.user, content="..."
        )
        msg.set_openai_id("xyz789")
        self.assertEqual(msg.openai_id, "xyz789")
