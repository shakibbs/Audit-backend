"""Module 12 step 2: each vendor's (and sub-ID's) scorecard, saved once a month (the current month is replaced every
night; earlier months stay as they were), giving the trend and the month-on-month drop alert."""
from django.db import models


class VendorMonth(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='vendor_months')
    period = models.DateField()  # first day of the month
    key = models.CharField(max_length=120)  # the vendor name, lower case and single spaces
    sub_id = models.CharField(max_length=60, blank=True)  # '' = the vendor row
    name = models.CharField(max_length=120)
    leads = models.PositiveIntegerField()
    rates = models.JSONField(default=dict)  # rate key → share 0–1, or null when not measured
    counts = models.JSONField(default=dict)
    score = models.FloatField(null=True, blank=True)  # 0–100, 100 = best; null = not enough data
    grade = models.CharField(max_length=1, blank=True)
    measured = models.PositiveIntegerField(default=0)  # how many of the six rates were measured
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vendor_month'
        constraints = [models.UniqueConstraint(fields=['client', 'period', 'key', 'sub_id'], name='one_vendor_row_per_month')]
        ordering = ['-period', 'key', 'sub_id']


def contract_path(contract, filename: str) -> str:
    import uuid
    from pathlib import Path
    return f'vendor-contracts/{contract.client_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class VendorContract(models.Model):
    """Module 12 step 3: a vendor contract the client uploaded. Kept private (never public, every opening logged) until
    the AI reader checks its clauses (Module 16), at most 4 years, then the file is deleted and its fingerprint kept
    (owner decision 2026-10-22). The newest upload per vendor counts."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='vendor_contracts')
    key = models.CharField(max_length=120)  # the vendor, as in vendor_month
    name = models.CharField(max_length=120)
    file = models.FileField(upload_to=contract_path, blank=True)
    original_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    ends_on = models.DateField(null=True, blank=True)  # empty = no end date stated
    dispute_days = models.PositiveIntegerField(null=True, blank=True)  # days to return a bad lead (step 4)
    clauses = models.JSONField(default=dict, blank=True)  # clause id → found / not found, filled by the AI reader later
    uploaded_by = models.CharField(max_length=200)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'vendor_contract'
        ordering = ['-uploaded_at']


class VendorLead(models.Model):
    """A lead from a vendor lead file the client uploaded (Upload centre, owner decision 2026-10-22), for clients whose
    leads do not pass through a CRM. Kept apart from CRM records so it never counts as a CRM import batch. The number
    is a phone code; the file itself is kept with the upload (4 years)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='vendor_leads')
    upload = models.ForeignKey('uploads.UploadedFile', on_delete=models.CASCADE, related_name='vendor_lead_rows')
    row = models.PositiveIntegerField()  # its line in the file
    lead_ref = models.CharField(max_length=120, blank=True)  # the vendor's lead ID, if the file gives one
    phone_token = models.CharField(max_length=64, db_index=True)
    vendor = models.CharField(max_length=120)
    sub_id = models.CharField(max_length=60, blank=True)
    received_at = models.DateTimeField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = 'vendor_lead'
        indexes = [models.Index(fields=['client', 'received_at'])]
