from pathlib import Path

from django.test import SimpleTestCase
from pydantic import ValidationError

from api.v1.schemas.trainerlab import VitalCreateIn


class VitalCreateInSchemaTests(SimpleTestCase):
    def test_accepts_respiratory_rate_vital_type(self) -> None:
        payload = {
            "vital_type": "respiratory_rate",
            "min_value": 12,
            "max_value": 20,
            "lock_value": False,
        }

        vital = VitalCreateIn.model_validate(payload)

        self.assertEqual(vital.vital_type, "respiratory_rate")

    def test_rejects_unknown_vital_type(self) -> None:
        payload = {
            "vital_type": "temperature",
            "min_value": 98,
            "max_value": 100,
            "lock_value": False,
        }

        with self.assertRaises(ValidationError):
            VitalCreateIn.model_validate(payload)


def test_apply_preset_outbox_idempotency_key_includes_command_id():
    source = Path("SimWorks/api/v1/endpoints/trainerlab.py").read_text()

    assert "trainerlab.preset.applied:{session.id}:{instruction.id}:{command.id}" in source
