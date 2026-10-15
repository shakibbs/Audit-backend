"""Runs one tool at one client: a small batch at a time, so every client gets a turn. The bookmark moves only after a
batch is fully processed, so a crash never skips or doubles a record."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.keyring.tokens import Tokenizer
from apps.ledger.record import ledger_job
from apps.tenancy.scope import tenant

from .connector import Record, connector_for
from .models import SyncCursor
from .process import process

KINDS = {'poll': 'changes_since', 'catchup': 'changes_since', 'full_sweep': 'list_all'}


def cursor_for(connection: Connection) -> SyncCursor:
    tool = connector_for(connection)
    cursor, _ = SyncCursor.objects.get_or_create(connection=connection, defaults={
        'client': connection.client, 'source_system': connection.provider, 'mode': tool.mode if tool else 'poll'})
    return cursor


def run(connection_id: int, kind: str) -> bool:
    """One batch. Returns True when the tool has more right now (the caller queues another turn)."""
    connection = Connection.objects.select_related('client').get(pk=connection_id)
    tool = connector_for(connection)
    if tool is None or not connection.client.can_sync:
        return False
    with tenant(connection.client):
        cursor = cursor_for(connection)
        start = cursor.sweep_cursor if kind == 'full_sweep' else cursor.cursor
        try:
            page = getattr(tool, KINDS[kind])(start, settings.SYNC_BATCH_SIZE)
            with ledger_job(connection.client, f'{connection.provider} {kind}') as job, transaction.atomic():
                process(job, cursor, page.records, kind, Tokenizer(connection.client))
                if kind == 'full_sweep':  # its own bookmark: the normal one keeps its place
                    cursor.sweep_cursor = page.next_cursor if page.more else ''
                else:
                    cursor.cursor, cursor.backlog = page.next_cursor, page.more
                now = timezone.now()
                cursor.last_heartbeat_at, cursor.failures_in_row, cursor.last_error = now, 0, ''
                if page.records:
                    cursor.last_event_at = now
                if kind == 'catchup' and not page.more:
                    cursor.last_catchup_at = now
                if kind == 'full_sweep' and not page.more:
                    cursor.last_full_sweep_at = now
                cursor.save()
        except Exception as error:  # the tool is down or answered wrongly: try again next turn
            cursor.failures_in_row += 1
            cursor.last_error = type(error).__name__
            SyncCursor.objects.filter(pk=cursor.pk).update(failures_in_row=cursor.failures_in_row, last_error=cursor.last_error)
            return False
    return page.more


def receive_live(connection: Connection, records: list[Record]) -> int:
    """Records from a live notice, processed at once. The bookmark is not moved: the catch-up keeps its own place."""
    with tenant(connection.client):
        cursor = cursor_for(connection)
        with ledger_job(connection.client, f'{connection.provider} live') as job, transaction.atomic():
            new = process(job, cursor, records, 'live', Tokenizer(connection.client))
            cursor.last_event_at = cursor.last_heartbeat_at = timezone.now()
            cursor.save()
    return new


def syncable() -> list[Connection]:
    """Connections the engine can read: a tool with an adapter, connected (or stale), at a client that may sync."""
    from .connector import CONNECTORS
    rows = Connection.objects.select_related('client').filter(provider__in=list(CONNECTORS), status__in=[Status.CONNECTED, Status.STALE])
    return [c for c in rows if c.client.can_sync]
