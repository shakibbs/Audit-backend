from django.apps import AppConfig


class ConnectionsConfig(AppConfig):
    name = 'apps.connections'
    label = 'connections'
    verbose_name = 'Connections'

    def ready(self):
        from apps.connections import signals  # noqa: F401
