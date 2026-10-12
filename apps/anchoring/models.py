from django.db import models


class MerkleAnchor(models.Model):
    """One client's fingerprints for one day, sealed into one root hash and stamped by outside services."""
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='anchors')
    day = models.DateField()  # the UTC day the fingerprints were read
    leaf_count = models.PositiveIntegerField()
    root = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    # RFC 3161 time stamp of the root: the signed answer, kept whole so anyone can check it later.
    tsa_url = models.CharField(max_length=200, blank=True)
    tsa_response = models.BinaryField(null=True, blank=True)
    tsa_time = models.DateTimeField(null=True, blank=True)
    # OpenTimestamps (Bitcoin): the calendar's pending proof; it becomes final once a Bitcoin block confirms it.
    ots_calendar = models.CharField(max_length=200, blank=True)
    ots_proof = models.BinaryField(null=True, blank=True)

    class Meta:
        db_table = 'merkle_anchor'
        indexes = [models.Index(fields=['client', 'day'])]
        ordering = ['-day']

    def __str__(self) -> str:
        return f'{self.client_id} · {self.day} · {self.leaf_count} fingerprints · {self.root[:12]}…'
