from django.apps import AppConfig


class OptoutsConfig(AppConfig):
    name = 'apps.optouts'
    label = 'optouts'
    verbose_name = 'Opt-outs'

    def ready(self):
        from apps.sync import handoff

        from .detect import optout_seen
        if optout_seen not in handoff.RECEIVERS:
            handoff.RECEIVERS.append(optout_seen)  # STOP texts and CRM "do not call" boxes, as they arrive
