"""Is CiV seeing every call and text? (spec §5b reconciliation, M37). Counts and ratios only."""
from django.db import models


class Reconciliation(models.Model):
    class Measure(models.TextChoices):
        CALLS = 'calls', 'Calls'
        TEXTS = 'texts', 'Texts'
        VENDOR_LEADS = 'vendor_leads', 'Vendor leads'
        CRM_RECORDS = 'crm_records', 'CRM records'
        DAYS_PRESENT = 'days_present', 'Days present'
        STOP_REPLIES = 'stop_replies', 'STOP replies'

    class Method(models.TextChoices):
        BILL = 'bill', 'Bill'  # strongest: CiV saw everything the client paid for
        TOOL_TOTAL = 'tool_total', "Tool's own total"  # CiV read everything the tool has
        VOLUME = 'volume', 'Volume pattern'  # nothing suddenly disappeared: days with records, no sudden drop
        NONE = 'none', 'Not checked'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='reconciliations')
    period = models.DateField()  # first day of the month
    measure = models.CharField(max_length=14, choices=Measure.choices)
    source_system = models.CharField(max_length=30, blank=True)  # which tool
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.NONE)  # how the second number was found
    records = models.PositiveIntegerField(null=True, blank=True)  # what CiV read
    independent_total = models.PositiveIntegerField(null=True, blank=True)  # the bill, the tool's own total, or working days
    ratio = models.FloatField(null=True, blank=True)
    available = models.BooleanField(default=True)  # False = no independent total: left out of M37, never failed
    flagged = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reconciliation'
        constraints = [models.UniqueConstraint(fields=['client', 'period', 'measure', 'source_system'], name='one_reconciliation_row')]


class PeriodIntegrity(models.Model):
    """One month for one client: records completeness (M37) and the contact volume (Exposure's Volume input)."""
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='period_integrity')
    period = models.DateField()
    completeness = models.FloatField(null=True, blank=True)  # M37: the lowest available ratio; None = nothing to compare
    floor = models.FloatField(default=0.9)
    incomplete = models.BooleanField(default=False)  # "incomplete data": the missing share takes worst-case values (Module 10)
    flagged_by = models.JSONField(default=list)  # every measure that flagged the month, M37 or not
    contacts = models.PositiveIntegerField(default=0)  # counted contacts in the month (Volume)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'period_integrity'
        constraints = [models.UniqueConstraint(fields=['client', 'period'], name='one_integrity_per_month')]
        ordering = ['-period']
