"""Module 14 step 2: the re-fetch check — CiV asks the tool for a record again and compares a new fingerprint of it with
the fingerprints it sealed. Only fingerprints are kept, never the record."""
from django.db import models


class RefetchCheck(models.Model):
    class Result(models.TextChoices):
        MATCHES = 'matches', 'Matches what CiV saw'
        CHANGED = 'changed', 'Changed since CiV saw it'
        GONE = 'gone', 'No longer at the source'
        CANNOT = 'cannot', 'This tool cannot be asked for one record'
        FAILED = 'failed', 'The tool did not answer'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='refetch_checks')
    source_system = models.CharField(max_length=40)
    source_record_id = models.CharField(max_length=200)
    checked_at = models.DateTimeField(auto_now_add=True)
    result = models.CharField(max_length=8, choices=Result.choices)
    sha256 = models.CharField(max_length=64, blank=True)  # of the record as the tool gave it now
    matched = models.ForeignKey('ledger.Fingerprint', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    why = models.CharField(max_length=20, blank=True)  # on_demand · weekly

    class Meta:
        db_table = 'refetch_check'
        indexes = [models.Index(fields=['client', 'source_system', 'source_record_id', 'checked_at'])]
        ordering = ['-checked_at']


class LegalHold(models.Model):
    """Module 14 step 4: while a dispute is open, nothing under the hold is deleted at its 4-year date (owner decision
    2026-10-22). A number is held by its phone code (never stored as typed), a vendor by its name key, a date range by
    its days. Fingerprints and seals are never deleted anyway; holds protect the files."""
    class Scope(models.TextChoices):
        NUMBER = 'number', 'A number'
        VENDOR = 'vendor', 'A vendor'
        DATES = 'date range', 'A date range'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='legal_holds')
    scope = models.CharField(max_length=10, choices=Scope.choices)
    target = models.CharField(max_length=120)  # what is shown: the masked number, the vendor's name or the dates
    phone_token = models.CharField(max_length=64, blank=True)
    vendor_key = models.CharField(max_length=120, blank=True)
    starts = models.DateField(null=True, blank=True)
    ends = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=300)
    set_by = models.CharField(max_length=200)
    set_at = models.DateTimeField(auto_now_add=True)
    released_by = models.CharField(max_length=200, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'legal_hold'
        ordering = ['-set_at']
