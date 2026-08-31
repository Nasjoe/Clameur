from django.apps import AppConfig


class CapsulesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "capsules"
    verbose_name = "Capsules"

    def ready(self):
        # Import a effet de bord : il enregistre les controles de deploiement.
        # Le nom importe n'est jamais reference — ne pas le supprimer.
        # / Side-effect import: it registers the deployment checks.
        from capsules import checks
