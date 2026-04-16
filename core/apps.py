from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Core (Drilling)'

    def ready(self):
        # Import signal handlers for websocket update broadcasts.
        from . import signals  # noqa: F401
