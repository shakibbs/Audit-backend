"""Industry-wide TCPA lawsuit numbers for the insurer's Litigation Intelligence page (Module 10 step 4b). Public
figures from WebRecon's monthly litigation statistics posts; not about any client, so not locked per client.
Company-level lawsuits (who was sued) come later from CourtListener (owner decision 2026-10-21)."""
from django.db import models


class LitigationMonth(models.Model):
    month = models.DateField(unique=True)  # first day of the month the figures cover
    source = models.CharField(max_length=30, default='webrecon')
    url = models.URLField(max_length=300)
    tcpa = models.PositiveIntegerField(null=True, blank=True)  # TCPA lawsuits filed in the month
    tcpa_class = models.PositiveIntegerField(null=True, blank=True)  # of which putative class actions
    tcpa_ytd = models.PositiveIntegerField(null=True, blank=True)  # TCPA lawsuits in the year up to this month
    change_month = models.FloatField(null=True, blank=True)  # % change the post gives for the month
    change_ytd = models.FloatField(null=True, blank=True)  # % change of the year to date vs the year before
    repeat_plaintiffs = models.FloatField(null=True, blank=True)  # % of the month's plaintiffs (all statutes) who had sued before
    read_ok = models.BooleanField(default=False)  # False: the post was found but its TCPA line could not be read
    fetched_at = models.DateTimeField(auto_now=True)
    page_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = 'litigation_month'
        ordering = ['-month']
