"""The Upload centre (Source Registry): files for the five sources that have no API. Each file is fingerprinted on
arrival, kept write-once (private, never changed, deleted after 4 years) and its rows are read into the tables below.
Phone numbers become phone codes while the file is read; no number, name or free text is kept in these tables."""
import uuid
from pathlib import Path

from django.db import models


class Source(models.TextChoices):
    INTERNAL_LIST = 'internal_list', 'Internal do-not-contact list'
    POLICIES = 'policies', 'Policies, training, contracts'
    COMPLAINTS = 'complaints', 'Complaint log'
    DNC_CHECKS = 'dnc_checks', 'DNC check records'
    RND_QUERIES = 'rnd_queries', 'Reassigned-number query logs'
    VENDOR_LEADS = 'vendor_leads', 'Vendor lead files'  # Module 12: leads that do not pass through a CRM


def upload_path(upload, filename: str) -> str:
    return f'client-uploads/{upload.client_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class UploadedFile(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='uploaded_files')
    source = models.CharField(max_length=20, choices=Source.choices)
    file = models.FileField(upload_to=upload_path, blank=True)  # private; deleted after 4 years, fingerprint kept
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    received_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey('accounts.ClientUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    rows_read = models.PositiveIntegerField(default=0)
    rows_rejected = models.PositiveIntegerField(default=0)
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'uploaded_file'
        ordering = ['-received_at']

    def __str__(self) -> str:
        return f'{self.get_source_display()} · {self.original_name}'


class InternalListEntry(models.Model):
    """A number on the client's own do-not-contact list, and since when (the upload date when the file gives none)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='internal_list')
    upload = models.ForeignKey(UploadedFile, on_delete=models.CASCADE, related_name='internal_entries')
    phone_token = models.CharField(max_length=64, db_index=True)
    added_on = models.DateField()

    class Meta:
        db_table = 'internal_list_entry'


class DncCheck(models.Model):
    """One number checked against a do-not-call list (national registry or a state list) by the client's DNC service."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='dnc_checks')
    upload = models.ForeignKey(UploadedFile, on_delete=models.CASCADE, related_name='dnc_rows')
    phone_token = models.CharField(max_length=64, db_index=True)
    checked_on = models.DateField()
    listed = models.BooleanField()
    list_name = models.CharField(max_length=40, blank=True)  # national, or a state code / list name as the file says

    class Meta:
        db_table = 'dnc_check'


class RndQuery(models.Model):
    """One reassigned-number query the client ran (FCC Reassigned Numbers Database): yes / no / no data."""
    class Result(models.TextChoices):
        YES = 'yes', 'Reassigned since the date asked'
        NO = 'no', 'Not reassigned'
        NO_DATA = 'no_data', 'No data'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='rnd_queries')
    upload = models.ForeignKey(UploadedFile, on_delete=models.CASCADE, related_name='rnd_rows')
    phone_token = models.CharField(max_length=64, db_index=True)
    queried_on = models.DateField()
    result = models.CharField(max_length=7, choices=Result.choices)

    class Meta:
        db_table = 'rnd_query'


class Complaint(models.Model):
    """A complaint from the client's log: when, how, whether and when it was resolved. Never the complaint's words."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='complaints')
    upload = models.ForeignKey(UploadedFile, on_delete=models.CASCADE, related_name='complaint_rows')
    phone_token = models.CharField(max_length=64, blank=True)
    received_on = models.DateField()
    resolved_on = models.DateField(null=True, blank=True)
    channel = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = 'complaint'


class TrainingRecord(models.Model):
    """An agent trained on a date. The agent is kept as a fingerprint of the ID the file gives (to count people), never a name."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='training_records')
    upload = models.ForeignKey(UploadedFile, on_delete=models.CASCADE, related_name='training_rows')
    agent_ref = models.CharField(max_length=64)
    trained_on = models.DateField()

    class Meta:
        db_table = 'training_record'
