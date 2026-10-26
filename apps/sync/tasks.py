"""The timetable: poll every 5 minutes, catch up every hour, full check weekly, health every 10 minutes.
Each run reads one small batch and queues the next turn at the back of the line, so clients take turns."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.tenancy.scope import all_clients

from . import engine, health
from .connector import connector_for
from .models import SyncCursor

log = logging.getLogger('civ.sync')


@shared_task(acks_late=True)
def sync_connection(connection_id: int, kind: str) -> None:
    if engine.run(connection_id, kind):
        sync_connection.delay(connection_id, kind)  # more waiting: back of the line, after other clients' batches


BUSY = timedelta(minutes=10)  # a backlog chain that moved in the last 10 minutes is still working


def broken(connection, error: Exception) -> None:
    """One connection that cannot even start (e.g. a wrong time zone) is marked Failed and skipped; the others go on."""
    from apps.connections.models import Status
    log.warning('Connection %s skipped: %r', connection.pk, error)
    message = f'Could not start reading: {error}'[:290]
    type(connection).objects.filter(pk=connection.pk).update(status=Status.FAILED, last_message=message, last_checked_at=timezone.now())


@shared_task
def poll_due() -> None:
    now = timezone.now()
    with all_clients():
        for connection in engine.syncable():
            try:
                cursor = engine.cursor_for(connection)
                gap = timedelta(minutes=connector_for(connection).min_poll_minutes)
            except Exception as error:
                broken(connection, error)
                continue
            if cursor.backlog and cursor.last_heartbeat_at and now - cursor.last_heartbeat_at < BUSY:
                continue  # its backlog chain is still reading: a second reader would read the same records
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
            try:
                cursor = engine.cursor_for(connection)
                connector_for(connection)
            except Exception as error:
                broken(connection, error)
                continue
            if cursor.last_full_sweep_at is None or cursor.last_full_sweep_at < week_ago:
                sync_connection.delay(connection.pk, 'full_sweep')


@shared_task
def check_health() -> None:
    with all_clients():
        health.check_all()
