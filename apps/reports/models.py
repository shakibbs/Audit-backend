"""Module 11 step 5: the monthly audit report (spec §9 "Period audit report"). CiV keeps its own reports (D33): the
PDF is private, kept 4 years (owner decision 2026-10-21), then deleted with its fingerprint kept. A report whose text
contains a banned word is blocked, not released. Other report types asked for on the Reports page are recorded as
"not available yet"."""
import uuid
from pathlib import Path

from django.db import models


def report_path(report, filename: str) -> str:
    return f'client-reports/{report.client_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower() or ".pdf"}'


class Report(models.Model):
    class Status(models.TextChoices):
        READY = 'ready', 'Ready'
        BLOCKED = 'blocked', 'Blocked (banned word)'
        UNAVAILABLE = 'unavailable', 'Not available yet'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='reports')
    name = models.CharField(max_length=120)
    period = models.DateField(null=True, blank=True)  # first day of the month
    status = models.CharField(max_length=11, choices=Status.choices)
    file = models.FileField(upload_to=report_path, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)  # of the PDF file
    content_sha256 = models.CharField(max_length=64, blank=True)  # of the figures it shows (printed in its footer)
    banned = models.JSONField(default=list, blank=True)  # the words that blocked it
    made_by = models.CharField(max_length=200)  # a user's name, or "CiV (automatic)"
    made_at = models.DateTimeField(auto_now_add=True)
    purged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'client report'
        verbose_name_plural = 'client reports'  # same words as the staff menu (2026-10-23)
        db_table = 'client_report'
        ordering = ['-made_at']

    def __str__(self):
        return ' · '.join(x for x in (self.name, f'{self.period:%b %Y}' if self.period else '', str(self.client)) if x)
