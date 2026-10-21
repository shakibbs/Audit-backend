"""Module 11 step 1: a finding is one problem CiV measured, in plain words (spec §9 "Findings"). One row per client and
problem; it is updated every night, closes by itself when a later night no longer finds the problem and reopens if it
comes back. Examples are masked labels and number-page references, never numbers."""
from django.db import models


class Finding(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        RESOLVED = 'resolved', 'Resolved'  # no longer found
        REOPENED = 'reopened', 'Reopened'

    class Severity(models.TextChoices):
        HIGH = 'High', 'High'
        MEDIUM = 'Medium', 'Medium'
        LOW = 'Low', 'Low'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='findings')
    key = models.CharField(max_length=30)  # the metric (and "worst" for missing data), e.g. M10, M12-worst
    metric = models.CharField(max_length=8)
    domain = models.CharField(max_length=8)
    severity = models.CharField(max_length=6, choices=Severity.choices)
    title = models.CharField(max_length=200)  # a noun phrase of what was observed (spec §9)
    why = models.CharField(max_length=400)
    affected = models.PositiveIntegerField(default=0)  # contacts (or items) affected, for ordering
    numbers = models.PositiveIntegerField(null=True, blank=True)  # distinct numbers affected, when known
    examples = models.JSONField(default=list)  # [{label, ref}] up to 5
    period = models.DateField()  # the saved month it was last found in
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.OPEN)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Step 2: what the client does with it (Admins and the company's lawyer). The note text stays in the client's own
    # workspace and is never sent to insurers; its fingerprint goes to the access log (spec §9 decision record).
    decision = models.CharField(max_length=11, blank=True, choices=[('accepted', 'Accepted'), ('declined', 'Declined'), ('alternative', 'Other plan')])
    decision_note = models.TextField(blank=True)
    note_sha256 = models.CharField(max_length=64, blank=True)
    decided_by = models.CharField(max_length=200, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    assignee = models.ForeignKey('accounts.ClientUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    due = models.DateField(null=True, blank=True)
    work_status = models.CharField(max_length=11, default='open', choices=[('open', 'Open'), ('in_progress', 'In progress'), ('resolved', 'Resolved')])
    dispute_note = models.TextField(blank=True)
    dispute_by = models.CharField(max_length=200, blank=True)
    dispute_at = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'finding'
        constraints = [models.UniqueConstraint(fields=['client', 'key'], name='one_finding_per_problem')]
