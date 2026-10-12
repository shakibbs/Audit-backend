from django.db import models
from django.db.models import Q


class ClientKey(models.Model):
    """Each client's secret key for phone codes, kept locked with the master key (D19: CiV holds it).
    Destroying it (contract end) makes every code for that client meaningless for good."""
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='keys')
    kid = models.CharField('key ID', max_length=16)  # saved next to every code, as phone_token_kid
    locked_key = models.TextField(blank=True)  # empty once destroyed
    created_at = models.DateTimeField(auto_now_add=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'client_key'
        constraints = [
            models.UniqueConstraint(fields=['client', 'kid'], name='client_key_kid_unique'),
            # At most one key in use per client.
            models.UniqueConstraint(fields=['client'], condition=Q(destroyed_at__isnull=True), name='client_key_one_active'),
        ]

    def __str__(self) -> str:
        return f'{self.client_id} · {self.kid}{" (destroyed)" if self.destroyed_at else ""}'
