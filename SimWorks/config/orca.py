# config/orca.py
from __future__ import annotations

from orchestrai import OrchestrAI
from orchestrai_django.integration import configure_from_django_settings

app = OrchestrAI()
configure_from_django_settings(app)
app.start()


def get_orca() -> OrchestrAI:
    return app
