from django.apps import AppConfig


class AdminpanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adminpanel"

    def ready(self):
        from . import schema  # noqa: F401  (registers OpenAPI auth extension)
