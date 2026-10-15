from django.apps import AppConfig


class CertificatesConfig(AppConfig):
    name = 'apps.certificates'
    label = 'certificates'
    verbose_name = 'Consent certificates'

    def ready(self):
        from apps.sync import handoff

        from .scan import scan_record
        if scan_record not in handoff.RECEIVERS:
            handoff.RECEIVERS.append(scan_record)  # every synced record is checked for certificate links
