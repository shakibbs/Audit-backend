"""One consent certificate CiV must claim in time, and the facts read from it. Never the person's details."""
from django.db import models


class CertificateClaim(models.Model):
    class Provider(models.TextChoices):
        TRUSTEDFORM = 'trustedform', 'TrustedForm'
        JORNAYA = 'jornaya', 'Jornaya'

    class State(models.TextChoices):
        WAITING = 'waiting', 'Waiting to be claimed'
        CLAIMED = 'claimed', 'Claimed'
        NO_KEY = 'no_key', 'No certificate account connected'
        LOST = 'lost', 'Lost: not claimed in time'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='certificate_claims')
    provider = models.CharField(max_length=20, choices=Provider.choices)
    cert_ref = models.CharField(max_length=80)  # the certificate's ID or token (evidence ID, not personal data)
    seen_at = models.DateTimeField(auto_now_add=True)  # when CiV first found it in a synced record
    deadline_at = models.DateTimeField()  # lead time + cert_unretained_expiry_hours (72): claim before this
    state = models.CharField(max_length=10, choices=State.choices, default=State.WAITING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=120, blank=True)  # the error's type only
    deadline_alerted = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    # Facts read from the certificate (judged in Modules 6 and 7).
    cert_created_at = models.DateTimeField(null=True, blank=True)
    cert_expires_at = models.DateTimeField(null=True, blank=True)
    page = models.CharField(max_length=300, blank=True)  # host and path only: a query string could carry personal data

    class Meta:
        db_table = 'certificate_claim'
        constraints = [models.UniqueConstraint(fields=['client', 'provider', 'cert_ref'], name='one_claim_per_certificate')]
        indexes = [models.Index(fields=['state', 'deadline_at'])]

    def __str__(self) -> str:
        return f'{self.get_provider_display()} {self.cert_ref[:12]}… · {self.get_state_display()}'
