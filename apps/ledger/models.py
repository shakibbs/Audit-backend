from django.db import models


class ContentKind(models.TextChoices):
    CALL = 'call', 'Call'
    TEXT = 'text', 'Text message'
    LEAD = 'lead', 'Lead'
    CERTIFICATE = 'certificate', 'Consent certificate'
    CRM_RECORD = 'crm_record', 'CRM record'
    PAGE_CAPTURE = 'page_capture', 'Page capture'
    BILLING = 'billing', 'Billing total'
    UPLOAD_ROW = 'upload_row', 'Uploaded row'


class SourceGrade(models.TextChoices):
    """Where the content came from (spec §4). S and N are never fingerprinted: nothing was read."""
    A = 'A', 'Source grade A · captured by CiV itself'
    B = 'B', 'Source grade B · from an independent third party'
    C = 'C', "Source grade C · from the client's systems by API"
    D = 'D', 'Source grade D · exported or uploaded by the client'


class Fingerprint(models.Model):
    """Proof of one record CiV read: its hash, where it came from and when. Never the record itself."""
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='fingerprints')
    job_id = models.UUIDField(db_index=True)  # the job that read it; a failed job's rows are removed together
    source_system = models.CharField(max_length=40)  # e.g. twilio, convoso
    source_record_id = models.CharField(max_length=200)  # the record's ID in that tool, to find the original again
    content_kind = models.CharField(max_length=20, choices=ContentKind.choices)
    source_grade = models.CharField(max_length=1, choices=SourceGrade.choices)
    sha256 = models.CharField(max_length=64)
    fetched_at = models.DateTimeField(db_index=True)
    # Filled by the nightly seal (apps.anchoring): which day's root it is in, and its path to that root.
    anchor = models.ForeignKey('anchoring.MerkleAnchor', on_delete=models.PROTECT, null=True, blank=True, related_name='fingerprints')
    leaf_index = models.PositiveIntegerField(null=True, blank=True)
    merkle_path = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'fingerprint'
        indexes = [models.Index(fields=['client', 'source_system', 'source_record_id'])]

    def __str__(self) -> str:
        return f'{self.source_system}:{self.source_record_id} · {self.sha256[:12]}…'


class PurgeLog(models.Model):
    """A job that failed part-way: how many of its rows were removed, and why. Holds no record content."""
    client = models.ForeignKey('clients.Client', on_delete=models.PROTECT, related_name='purges')
    job_id = models.UUIDField()
    job_name = models.CharField(max_length=80)
    failed_at = models.DateTimeField(auto_now_add=True)
    rows_removed = models.PositiveIntegerField()
    reason = models.CharField(max_length=120)  # the error's type only: its message could quote a record

    class Meta:
        db_table = 'purge_log'
        ordering = ['-failed_at']
        verbose_name = 'failed-job cleanup'

    def __str__(self) -> str:
        return f'{self.job_name} · {self.rows_removed} removed · {self.reason}'
