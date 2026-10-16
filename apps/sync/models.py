"""Live sync bookkeeping (spec: sync_cursor, sync_gap). Never a record's content."""
from django.db import models


class SyncCursor(models.Model):
    """Where CiV stopped reading one tool at one client, and how that tool is doing."""
    class Mode(models.TextChoices):
        LIVE = 'live', 'Live notices'
        POLL = 'poll', 'Polling'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='sync_cursors')
    connection = models.OneToOneField('connections.Connection', on_delete=models.CASCADE, related_name='sync')
    source_system = models.CharField(max_length=30)
    cursor = models.CharField(max_length=500, blank=True)  # the tool's change token, or a timestamp
    sweep_cursor = models.CharField(max_length=500, blank=True)  # where the running weekly full check is; empty = start
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.POLL)
    last_event_at = models.DateTimeField(null=True, blank=True)  # last record or live notice received
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)  # last successful call to the tool
    last_catchup_at = models.DateTimeField(null=True, blank=True)
    last_full_sweep_at = models.DateTimeField(null=True, blank=True)
    backlog = models.BooleanField(default=False)  # the tool still had more when the last run stopped
    records_delivered = models.PositiveBigIntegerField(default=0)
    failures_in_row = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=120, blank=True)  # the error's type only: a message could quote a record

    class Meta:
        db_table = 'sync_cursor'

    def __str__(self) -> str:
        return f'{self.source_system} · {self.cursor or "start"}'


class SyncGap(models.Model):
    """A change the live feed should have sent but the catch-up (or full check) found instead."""
    class FoundBy(models.TextChoices):
        CATCHUP = 'catchup', 'Hourly catch-up'
        FULL_SWEEP = 'full_sweep', 'Weekly full check'

    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='sync_gaps')
    source_system = models.CharField(max_length=30)
    source_record_id = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    found_by = models.CharField(max_length=12, choices=FoundBy.choices)
    changed_at = models.DateTimeField()
    found_at = models.DateTimeField(auto_now_add=True)
    delay_seconds = models.PositiveIntegerField()

    class Meta:
        db_table = 'sync_gap'
        ordering = ['-found_at']
        verbose_name = 'missed record'
