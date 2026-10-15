"""Live / Catching up / Stale for each tool. Quiet for longer than source_freshness_hours (Rulebook: 2) = stale."""
from datetime import timedelta

from django.utils import timezone

from apps.access_log.recorder import record
from apps.connections.access_level import refresh_access_level
from apps.connections.models import Connection, Status
from apps.rulebook.lookup import NoRulebook, RuleSet

from .models import SyncCursor

DEFAULT_FRESH_HOURS = 2


def fresh_hours() -> int:
    try:
        return RuleSet().get('source_freshness_hours', on=timezone.localdate()).value or DEFAULT_FRESH_HOURS
    except NoRulebook:
        return DEFAULT_FRESH_HOURS


def state(cursor: SyncCursor | None, now=None) -> str:
    """'live', 'catching_up', 'stale' or 'never' (not read yet)."""
    now = now or timezone.now()
    if cursor is None or cursor.last_heartbeat_at is None:
        return 'never'
    if now - cursor.last_heartbeat_at > timedelta(hours=fresh_hours()):
        return 'stale'
    return 'catching_up' if cursor.backlog else 'live'


def check_all() -> list[Connection]:
    """Marks quiet tools stale (logged once, which is the alert until Module 11) and brings recovered ones back.
    Returns the connections that just went stale."""
    went_stale = []
    for cursor in SyncCursor.objects.select_related('connection', 'client'):
        connection, now_state = cursor.connection, state(cursor)
        if now_state == 'stale' and connection.status == Status.CONNECTED:
            connection.status = Status.STALE
            connection.last_message = f'No news for over {fresh_hours()} hours'
            connection.save(update_fields=['status', 'last_message', 'updated_at'])
            record('source_stale', client_id=cursor.client_id, object=str(connection)[:254])
            went_stale.append(connection)
        elif now_state in ('live', 'catching_up') and connection.status == Status.STALE:
            connection.status, connection.last_message = Status.CONNECTED, ''
            connection.save(update_fields=['status', 'last_message', 'updated_at'])
            record('source_recovered', client_id=cursor.client_id, object=str(connection)[:254])
        refresh_access_level(cursor.client)
    return went_stale
