"""Unit tests for GenerateInitialFeedback transcript grounding.

Validates:
- Service prepares transcript context from canonical simulation messages
- Empty-transcript path sets an explicit fallback user_message
- Grounded user_message contains actual transcript content
- FeedbackInitialInstruction contains required grounding language
"""

import pathlib
import types

import pytest

from apps.simcore.orca.services.feedback import GenerateInitialFeedback

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_history(*pairs):
    """Build list of history dicts matching the chatlab history provider format."""
    return [
        {"role": role, "sender": sender, "content": content, "timestamp": None}
        for role, sender, content in pairs
    ]


def _make_mock_sim(history_data):
    """Return a lightweight mock simulation object."""
    sim = types.SimpleNamespace()
    sim.history = lambda _format=None: history_data
    return sim


def _patch_simulation(monkeypatch, sim_obj):
    """Monkeypatch Simulation.objects.aget to return sim_obj."""

    class _Manager:
        async def aget(self, **_kwargs):
            return sim_obj

    class _FakeSim:
        objects = _Manager()

    import apps.simcore.orca.services.feedback as feedback_module

    monkeypatch.setattr(feedback_module, "Simulation", _FakeSim, raising=False)

    # Also patch the import inside _aprepare_context (late import path)
    import sys

    fake_simcore = types.ModuleType("apps.simcore.models")
    fake_simcore.Simulation = _FakeSim
    monkeypatch.setitem(sys.modules, "apps.simcore.models", fake_simcore)


# ---------------------------------------------------------------------------
# Test A — Service prepares transcript context from messages
# ---------------------------------------------------------------------------


class TestPrepareTranscriptContext:
    @pytest.mark.asyncio
    async def test_transcript_and_user_message_set_from_history(self, monkeypatch):
        history = _make_history(
            ("A", "Patient", "I have chest pain."),
            ("U", "Learner", "How long have you had it?"),
            ("A", "Patient", "About an hour."),
        )
        sim = _make_mock_sim(history)
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 42})
        await service._aprepare_context()

        assert service.context.get("transcript"), "transcript must be set and non-empty"
        assert service.context.get("user_message"), "user_message must be set and non-empty"

    @pytest.mark.asyncio
    async def test_transcript_contains_message_content(self, monkeypatch):
        history = _make_history(
            ("A", "Patient", "I have chest pain."),
            ("U", "Learner", "How long have you had it?"),
        )
        sim = _make_mock_sim(history)
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 42})
        await service._aprepare_context()

        transcript = service.context.get("transcript", "")
        assert "chest pain" in transcript
        assert "How long" in transcript

    @pytest.mark.asyncio
    async def test_user_message_references_simulation_or_transcript(self, monkeypatch):
        history = _make_history(("A", "Patient", "Hello."), ("U", "Learner", "Hi there."))
        sim = _make_mock_sim(history)
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 42})
        await service._aprepare_context()

        user_msg = service.context.get("user_message", "").lower()
        assert "simulation" in user_msg or "transcript" in user_msg

    @pytest.mark.asyncio
    async def test_messages_are_chronologically_included(self, monkeypatch):
        history = _make_history(
            ("U", "Learner", "First message"),
            ("A", "Patient", "Second message"),
            ("U", "Learner", "Third message"),
        )
        sim = _make_mock_sim(history)
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 42})
        await service._aprepare_context()

        transcript = service.context.get("transcript", "")
        assert transcript.index("First") < transcript.index("Second") < transcript.index("Third")


# ---------------------------------------------------------------------------
# Test B — Empty transcript handled gracefully
# ---------------------------------------------------------------------------


class TestEmptyTranscriptFallback:
    @pytest.mark.asyncio
    async def test_empty_history_sets_fallback_user_message(self, monkeypatch):
        sim = _make_mock_sim([])
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 99})
        await service._aprepare_context()

        user_msg = service.context.get("user_message", "").lower()
        assert "unavailable" in user_msg or "no messages" in user_msg or "incomplete" in user_msg

    @pytest.mark.asyncio
    async def test_empty_history_does_not_crash(self, monkeypatch):
        sim = _make_mock_sim([])
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 99})
        # Must not raise
        await service._aprepare_context()

    @pytest.mark.asyncio
    async def test_empty_content_messages_are_filtered(self, monkeypatch):
        history = [
            {"role": "A", "sender": "Patient", "content": "", "timestamp": None},
            {"role": "U", "sender": "Learner", "content": None, "timestamp": None},
        ]
        sim = _make_mock_sim(history)
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 99})
        await service._aprepare_context()

        # All content was empty — should hit the empty-transcript fallback
        user_msg = service.context.get("user_message", "").lower()
        assert "unavailable" in user_msg or "no messages" in user_msg or "incomplete" in user_msg


# ---------------------------------------------------------------------------
# Test C — Grounding regression: actual transcript content reaches user_message
# ---------------------------------------------------------------------------


class TestGroundingRegression:
    @pytest.mark.asyncio
    async def test_specific_clinical_content_appears_in_user_message(self, monkeypatch):
        history = _make_history(
            ("U", "Learner", "Do you have any allergies?"),
            ("A", "Patient", "I am allergic to penicillin."),
            ("U", "Learner", "I am giving you aspirin."),
        )
        sim = _make_mock_sim(history)
        _patch_simulation(monkeypatch, sim)

        service = GenerateInitialFeedback(context={"simulation_id": 7})
        await service._aprepare_context()

        user_msg = service.context.get("user_message", "")
        assert "aspirin" in user_msg, "user_message must contain grounded transcript content"
        assert "penicillin" in user_msg

    @pytest.mark.asyncio
    async def test_explicit_caller_user_message_is_not_overwritten(self, monkeypatch):
        sim = _make_mock_sim(_make_history(("A", "Patient", "Hello.")))
        _patch_simulation(monkeypatch, sim)

        caller_msg = "Custom caller-provided evaluation prompt."
        service = GenerateInitialFeedback(context={"simulation_id": 7, "user_message": caller_msg})
        await service._aprepare_context()

        assert service.context["user_message"] == caller_msg


# ---------------------------------------------------------------------------
# Test D — Instruction regression: grounding language present in YAML
# ---------------------------------------------------------------------------


class TestInstructionGroundingLanguage:
    def _load_instruction_text(self):
        yaml_path = (
            pathlib.Path(__file__).parents[2]
            / "SimWorks/apps/simcore/orca/instructions/feedback.yaml"
        )
        return yaml_path.read_text()

    def test_instruction_requires_actual_simulation_transcript(self):
        text = self._load_instruction_text()
        assert "simulation transcript" in text.lower(), (
            "FeedbackInitialInstruction must reference 'simulation transcript'"
        )

    def test_instruction_prohibits_invention(self):
        text = self._load_instruction_text()
        assert "do not invent" in text.lower(), (
            "FeedbackInitialInstruction must say 'Do not invent'"
        )

    def test_instruction_requires_specific_learner_actions(self):
        text = self._load_instruction_text()
        assert "specific learner" in text.lower() or "reference specific" in text.lower(), (
            "FeedbackInitialInstruction must require reference to specific learner actions"
        )

    def test_instruction_requires_diagnosis_first_in_narrative(self):
        text = self._load_instruction_text()
        assert "first 1-2 sentences" in text.lower(), (
            "FeedbackInitialInstruction must require correct diagnosis in first 1-2 sentences"
        )
