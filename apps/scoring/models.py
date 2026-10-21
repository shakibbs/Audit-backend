"""Module 10 step 1: a saved copy of every metric for each client and month (spec: metric_snapshot). Pages read these
instead of counting again. A month is open while it runs and for LOCK_DAYS after; then it is locked. A locked month is
never overwritten: if late data or a rule change gives different results, a new version is saved, marked revised."""
from django.db import models


class SnapshotRun(models.Model):
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='snapshot_runs')
    period = models.DateField()  # first day of the month
    version = models.PositiveIntegerField(default=1)
    ran_at = models.DateTimeField()
    locked = models.BooleanField(default=False)
    revised = models.BooleanField(default=False)  # a newer version of a month that was already locked
    fingerprint = models.CharField(max_length=64)  # of the metric values, to see whether a re-check changed anything
    contacts = models.PositiveIntegerField(default=0)  # outbound contacts in the month: the base for counts per 10,000
    score = models.JSONField(default=dict)  # step 3: {factors: [F1–F6 with value / pending / heldBy], defect: D, partial}

    class Meta:
        db_table = 'snapshot_run'
        constraints = [models.UniqueConstraint(fields=['client', 'period', 'version'], name='one_snapshot_version')]
        ordering = ['-period', '-version']


class MetricSnapshot(models.Model):
    class State(models.TextChoices):
        MEASURED = 'measured', 'Measured'
        NOT_MEASURED = 'not_measured', 'Not yet measured'  # CiV can't measure it yet, or no data in the month
        WORST_CASE = 'worst_case', 'Worst case'  # the client did not supply the data
        RULE_PENDING = 'rule_pending', 'Rule pending'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='metric_snapshots')
    run = models.ForeignKey(SnapshotRun, on_delete=models.CASCADE, related_name='metrics')
    code = models.CharField(max_length=8)
    value = models.FloatField(null=True, blank=True)
    display = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=12, choices=State.choices)
    score = models.FloatField(null=True, blank=True)  # 0–100, 100 = best (step 2); empty = not scored
    data = models.JSONField(default=dict)  # the metric as the portal gets it (note, evidence, source…)

    class Meta:
        db_table = 'metric_snapshot'
        constraints = [models.UniqueConstraint(fields=['run', 'code'], name='one_metric_per_run')]
