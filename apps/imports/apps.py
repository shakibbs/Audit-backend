from django.apps import AppConfig


class ImportsConfig(AppConfig):
    name = 'apps.imports'
    label = 'imports'
    verbose_name = 'Import batches'

    def ready(self):
        from apps.sync import handoff

        from .creations import creation_seen
        if creation_seen not in handoff.RECEIVERS:
            handoff.RECEIVERS.append(creation_seen)  # every CRM person or lead: when, by whom (ID), how it was created
