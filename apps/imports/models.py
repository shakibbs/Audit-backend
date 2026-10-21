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
    vendor = models.CharField(max_length=120, blank=True)  # the lead's vendor as the CRM names it (lead provenance, Module 8)
    # Update uploads (Module 8): a fingerprint of the opt-out, do-not-call and lead-source fields, never their values,
    # and whether the record is marked opted out now.
    watched_sha = models.CharField(max_length=64, blank=True)
    opted_out = models.BooleanField(null=True)
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
    system = models.CharField(max_length=10, default='crm')  # crm (records created) · crm_update (records updated) · dialer (dialer lists)
    source_system = models.CharField(max_length=30)
    created_by = models.CharField(max_length=120, blank=True)
    starts = models.DateTimeField()
    ends = models.DateTimeField()
    created_count = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=14, choices=Kind.choices)
    labelled_by_tool = models.BooleanField(default=False)  # the tool itself said "import"
    confirmed_by_client = models.BooleanField(null=True)  # spec: the client confirms detected batches (later)
    opted_out_readded = models.PositiveIntegerField(default=0)  # Module 5 step 2
    updated_count = models.PositiveIntegerField(default=0)  # crm_update: records the upload changed
    optouts_cleared = models.PositiveIntegerField(default=0)  # crm_update: opted-out records the upload un-marked
    list_id = models.CharField(max_length=60, blank=True)  # dialer: the dialer's list

    class Meta:
        db_table = 'import_batch'
        ordering = ['-starts']

    def __str__(self) -> str:
        return f'{self.get_kind_display()} · {self.created_count} records · {self.starts:%Y-%m-%d %H:%M}'


class CrmUpdate(models.Model):
    """A CRM record that came back with its opt-out, do-not-call or lead-source fields changed: who, when (Module 8)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='crm_updates')
    source_system = models.CharField(max_length=30)
    record_id = models.CharField(max_length=200)
    updated_at = models.DateTimeField()
    updated_by = models.CharField(max_length=120, blank=True)
    cleared_optout = models.BooleanField(default=False)  # it was marked opted out and no longer is
    phone_tokens = models.JSONField(default=list)
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='updates')

    class Meta:
        db_table = 'crm_update'
        indexes = [models.Index(fields=['client', 'source_system', 'updated_by', 'updated_at'])]


class DialerListEntry(models.Model):
    """A number added to a dialer list (Vicidial, Convoso): which list and when. The number only as a phone code."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='dialer_list_entries')
    source_system = models.CharField(max_length=30)
    lead_id = models.CharField(max_length=60)  # the dialer's own ID for the entry
    list_id = models.CharField(max_length=60)
    added_at = models.DateTimeField()
    phone_token = models.CharField(max_length=64)
    batch = models.ForeignKey(ImportBatch, on_delete=models.SET_NULL, null=True, blank=True, related_name='dialer_entries')

    class Meta:
        db_table = 'dialer_list_entry'
        constraints = [models.UniqueConstraint(fields=['client', 'source_system', 'lead_id'], name='one_dialer_entry')]
        indexes = [models.Index(fields=['client', 'source_system', 'list_id', 'added_at'])]
