"""Module 11 step 5: the monthly audit report (spec §9 "Period audit report"). CiV keeps its own reports (D33): the
PDF is private, kept 4 years (owner decision 2026-10-21), then deleted with its fingerprint kept. A report whose text
contains a banned word is blocked, not released. The evidence file and certification pack are made from the bulk export;
the litigation package is a paid add-on, asked for as a quote request (2026-10-30)."""
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


def package_path(q, filename: str) -> str:
    return f'client-packages/{q.client_id}/{uuid.uuid4().hex}.zip'


class QuoteRequest(models.Model):
    """A client asked for the litigation evidence package (2026-10-30). The steps: the client asks; CiV staff contact
    them, agree the price and press Accept; the client types up to 25 numbers and CiV makes the package; staff check it
    and press Release (the custodian declaration gets their name); the client downloads it. Every step is logged."""
    class Status(models.TextChoices):
        ASKED = 'asked', 'Waiting for CiV'
        ACCEPTED = 'accepted', 'Accepted: waiting for the numbers'
        CHECKING = 'checking', 'Package made: check it'
        RELEASED = 'released', 'Released to the client'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='quote_requests')
    name = models.CharField(max_length=120)  # the add-on asked for
    period = models.DateField(null=True, blank=True)  # the month the page showed
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ASKED)
    asked_by = models.CharField(max_length=200)
    asked_by_email = models.EmailField(blank=True)
    asked_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.CharField(max_length=254, blank=True)
    package = models.FileField(upload_to=package_path, blank=True)  # private: downloaded only through CiV, logged
    package_sha256 = models.CharField(max_length=64, blank=True)
    package_files = models.PositiveIntegerField(default=0)  # numbers CiV found
    package_missing = models.PositiveIntegerField(default=0)  # numbers CiV holds nothing for
    made_at = models.DateTimeField(null=True, blank=True)
    made_by = models.CharField(max_length=200, blank=True)
    custodian_name = models.CharField('custodian name', max_length=150, blank=True, help_text='The CiV person named in the custodian declaration.')
    custodian_title = models.CharField('custodian title', max_length=150, blank=True, help_text='Their job title at Comply iV.')
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.CharField(max_length=254, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)  # closed: the client can ask again
    done_by = models.CharField(max_length=254, blank=True)
    note = models.TextField(blank=True)  # what CiV agreed with the client (price, numbers, lawyer)

    class Meta:
        verbose_name = 'quote request'
        verbose_name_plural = 'quote requests'
        db_table = 'client_quote_request'
        ordering = ['-asked_at']

    def __str__(self):
        return f'{self.name} · {self.client} · {self.asked_at:%d %b %Y}'
