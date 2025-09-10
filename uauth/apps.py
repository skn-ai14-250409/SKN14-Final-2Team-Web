from django.apps import AppConfig

class UauthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'uauth'

    def ready(self):
        from . import signals
