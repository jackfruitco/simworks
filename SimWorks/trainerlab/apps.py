from django.apps import AppConfig


class TrainerlabConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'trainerlab'

    # e.g. {"app", "App", "AppName"}
    # simcore_ai_django already adds all app names to this (normed)
    identity_strip_tokens = {}
