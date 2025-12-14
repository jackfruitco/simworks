# config/orca.py
from __future__ import annotations

from orchestrai_django import OrchestrAI

app = OrchestrAI()
app.AppConfig.from_object("django.conf:settings", namespace="ORCA")

def get_orca() -> OrchestrAI:
    return app