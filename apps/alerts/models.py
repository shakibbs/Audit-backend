"""Module 11 step 3: one alert per thing that needs someone to look now (spec §9 "Alerts"). Portal only, no email
(owner decision 2026-10-16). The same open problem updates its alert instead of making a new one; a condition that
goes away marks it resolved; reviewed and resolved alerts are kept forever (they show the company was told)."""
from django.db import models


class Alert(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='alerts')
    key = models.CharField(max_length=80)  # what it is about, e.g. stale-12, after-optout-2026-10-21
    kind = models.CharField(max_length=60)
    severity = models.CharField(max_length=6)  # High · Medium · Low
    title = models.CharField(max_length=200)
    detail = models.CharField(max_length=400)
    domain = models.CharField(max_length=8)
    count = models.PositiveIntegerField(default=1)
    first_at = models.DateTimeField()
    at = models.DateTimeField()  # last time it was raised or updated
    resolved_at = models.DateTimeField(null=True, blank=True)
    reviewed = models.BooleanField(default=False)
    reviewed_by = models.CharField(max_length=200, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)  # when the company's Admins were emailed about it

    class Meta:
        db_table = 'alert'
        constraints = [models.UniqueConstraint(fields=['client', 'key'], name='one_alert_per_key')]
        ordering = ['-at']


class EmailChoice(models.Model):
    """Which alert types a company's Admins also get by email (owner decision 2026-10-23; Admins only). A type with no
    row uses DEFAULT_EMAIL in apps.alerts.emails."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='alert_email_choices')
    kind = models.CharField(max_length=30)  # after-optout · page-change · cert-expiry · test-deadline · source-stale · vendor-drop · rule-change
    email = models.BooleanField()
    by = models.CharField(max_length=150)
    at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'alert_email_choice'
        constraints = [models.UniqueConstraint(fields=['client', 'kind'], name='one_email_choice_per_kind')]
