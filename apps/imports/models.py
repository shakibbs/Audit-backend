"""Lists uploaded by hand (spec §5a): when and by whom each CRM record was created, grouped into batches.
Only user IDs and times, never a name, an email or a file name."""
from django.db import models


class CrmCreation(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='crm_creations')
    source_system = models.CharField(max_length=30)  # salesforce, hubspot
    record_id = models.CharField(max_length=200)
    created_at = models.DateTimeField()
    created_by = models.CharField(max_length=120, blank=True)  # the CRM's user ID
    how = models.CharField(max_length=30, blank=True)  # the tool's own label when it gives one (HubSpot: IMPORT, FORM…)
    phone_tokens = models.JSONField(default=list)
    batch = models.ForeignKey('imports.ImportBatch', on_delete=models.SET_NULL, null=True, blank=True, related_name='records')

    class Meta:
        db_table = 'crm_creation'
        constraints = [models.UniqueConstraint(fields=['client', 'source_system', 'record_id'], name='one_creation_per_record')]
        indexes = [models.Index(fields=['client', 'source_system', 'created_by', 'created_at'])]


class ImportBatch(models.Model):
    class Kind(models.TextChoices):
        BULK = 'bulk_import', 'Bulk import (uploaded list)'
        SMALL = 'small_batch', 'Small batch'
        HAND = 'hand_entered', 'Typed by hand'
        FEED = 'feed', 'Automatic feed'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='import_batches')
    system = models.CharField(max_length=10, default='crm')  # crm (dialer-side imports later)
    source_system = models.CharField(max_length=30)
    created_by = models.CharField(max_length=120, blank=True)
    starts = models.DateTimeField()
    ends = models.DateTimeField()
    created_count = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=14, choices=Kind.choices)
    labelled_by_tool = models.BooleanField(default=False)  # the tool itself said "import"
    confirmed_by_client = models.BooleanField(null=True)  # spec: the client confirms detected batches (later)
    opted_out_readded = models.PositiveIntegerField(default=0)  # Module 5 step 2

    class Meta:
        db_table = 'import_batch'
        ordering = ['-starts']

    def __str__(self) -> str:
        return f'{self.get_kind_display()} · {self.created_count} records · {self.starts:%Y-%m-%d %H:%M}'
