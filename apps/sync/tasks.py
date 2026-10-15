"""The timetable: poll every 5 minutes, catch up every hour, full check weekly, health every 10 minutes.
Each run reads one small batch and queues the next turn at the back of the line, so clients take turns."""
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.tenancy.scope import all_clients

from . import engine, health
from .connector import connector_for
from .models import SyncCursor


@shared_task(acks_late=True)
def sync_connection(connection_id: int, kind: str) -> None:
    if engine.run(connection_id, kind):
        sync_connection.delay(connection_id, kind)  # more waiting: back of the line, after other clients' batches


@shared_task
def poll_due() -> None:
    now = timezone.now()
    with all_clients():
        for connection in engine.syncable():
            cursor = engine.cursor_for(connection)
            gap = timedelta(minutes=connector_for(connection).min_poll_minutes)
            if cursor.mode == SyncCursor.Mode.POLL and (cursor.last_heartbeat_at is None or now - cursor.last_heartbeat_at >= gap):
                sync_connection.delay(connection.pk, 'poll')


@shared_task
def catchup_all() -> None:
    with all_clients():
        for connection in engine.syncable():
            sync_connection.delay(connection.pk, 'catchup')


@shared_task
def full_sweep_due() -> None:
    week_ago = timezone.now() - timedelta(days=7)
    with all_clients():
        for connection in engine.syncable():
            cursor = engine.cursor_for(connection)
            if cursor.last_full_sweep_at is None or cursor.last_full_sweep_at < week_ago:
                sync_connection.delay(connection.pk, 'full_sweep')


@shared_task
def check_health() -> None:
    with all_clients():
        health.check_all()
