from django.apps import AppConfig


class SyncConfig(AppConfig):
    name = 'apps.sync'
    label = 'sync'
    verbose_name = 'Live sync'

    def ready(self):
        from . import connectors  # noqa: F401  (each tool registers its adapter)
