import pytest
from django.test import TestCase
from .models import Prompt, Response
from .factories import UserFactory, SimulationFactory

class PromptModelTest(TestCase):

    @pytest.mark.django_db
    def test_str_returns_title(self):
        prompt = Prompt(title="Test Title")
        assert str(prompt) == "Test Title"

    @pytest.mark.django_db
    def test_is_active_returns_true_when_not_archived(self):
        prompt = Prompt(archived=False)
        assert prompt.is_active is True

    @pytest.mark.django_db
    def test_is_active_returns_false_when_archived(self):
        prompt = Prompt(archived=True)
        assert prompt.is_active is False

    @pytest.mark.django_db
    def test_compute_own_fingerprint_generates_expected_value(self):
        prompt = Prompt()
        expected_fingerprint = prompt.compute_fingerprint()
        assert prompt.compute_own_fingerprint() == expected_fingerprint

    @pytest.mark.django_db
    def test_save_sets_modified_by(self):
        user = UserFactory()
        prompt = Prompt()
        prompt.set_modified_by(user)
        prompt.save()
        assert prompt.modified_by == user

class ResponseModelTest(TestCase):

    @pytest.mark.django_db
    def test_str_returns_expected_format(self):
        response = Response(text="Sample Response")
        assert str(response) == "Sample Response"

    @pytest.mark.django_db
    def test_tally_correctly_sums_tokens(self):
        response = Response(tokens=[1, 2, 3])
        assert response.tally() == 6

    @pytest.mark.django_db
    def test_save_assigns_order_correctly_when_none(self):
        response = Response()
        response.save()
        assert response.order is not None

    @pytest.mark.django_db
    def test_unique_together_constraint_on_simulation_and_order(self):
        simulation = SimulationFactory()
        response1 = Response(simulation=simulation, order=1)
        response1.save()
        response2 = Response(simulation=simulation, order=1)
        with pytest.raises(Exception):
            response2.save()
