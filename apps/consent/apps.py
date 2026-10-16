from django.apps import AppConfig


class ConsentConfig(AppConfig):
    name = 'apps.consent'
    label = 'consent'
    verbose_name = 'Consent'

    def ready(self):
        from apps.sync import handoff

        from .proofs import proofs_seen
        if proofs_seen not in handoff.RECEIVERS:
            handoff.RECEIVERS.append(proofs_seen)  # after the certificate scanner: its claims exist by now
