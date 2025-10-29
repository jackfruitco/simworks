# tests/fixtures/dummyapp/apps.py
from django.apps import AppConfig

class DummyappConfig(AppConfig):
    name = "tests.simcore_ai_django.fixtures.dummyapp"
    label = "dummyapp"  # app_label used in identity derivation
    verbose_name = "Dummy Identity Test App"

    # Tokens used by Django identity derivation
    IDENTITY_STRIP_TOKENS = ("Generate", "Response", "Service")