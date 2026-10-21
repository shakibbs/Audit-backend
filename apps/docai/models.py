"""Module 16: one reading of one document by the document AI, kept with the AI's name and instructions version. The
same file (same SHA-256) with the same instructions is never read twice. Applied to the record only when the AI had
passed its exam for that kind of document and was sure enough."""
from django.db import models


class DocReading(models.Model):
    class Status(models.TextChoices):
        WAITING = 'waiting', 'Waiting for the AI'
        DONE = 'done', 'Read'
        UNCLEAR = 'unclear', 'Read, not sure enough'
        FAILED = 'failed', 'Could not be read'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='doc_readings')
    feature = models.CharField(max_length=30)  # contract_clauses · consent_page · policy_file
    ref = models.CharField(max_length=60)  # what was read, e.g. vendor_contract:12
    input_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    answers = models.JSONField(default=dict, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    model = models.CharField(max_length=60, blank=True)
    prompt_version = models.CharField(max_length=20)
    trusted = models.BooleanField(default=False)  # the AI had passed its exam for this feature
    applied = models.BooleanField(default=False)  # its answers were written into the record
    note = models.CharField(max_length=200, blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'doc_reading'
        constraints = [models.UniqueConstraint(fields=['client', 'feature', 'ref', 'input_sha256', 'prompt_version'], name='one_reading_per_input')]
        ordering = ['-queued_at']


class DocExamRun(models.Model):
    """The document AI's exam for one feature: hand-checked examples with known answers (the accuracy gate)."""
    feature = models.CharField(max_length=30)
    model = models.CharField(max_length=60)
    prompt_version = models.CharField(max_length=20)
    cases = models.PositiveIntegerField(default=0)
    right = models.PositiveIntegerField(default=0)
    passed = models.BooleanField(default=False)
    mistakes = models.JSONField(default=list, blank=True)
    note = models.CharField(max_length=200, blank=True)
    ran_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'doc_exam_run'
        ordering = ['-ran_at']
