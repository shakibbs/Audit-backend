"""Reads which numbers were put into which dialer list, and when (Module 8, dialer-side uploads). Vicidial from its
database (vicidial_list, SELECT only); Convoso from its lead search API (built from the docs, TO CONFIRM). Five9: later.
Numbers become phone codes in memory and are never stored."""
from datetime import UTC, datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import BigIntegerField, Max
from django.db.models.functions import Cast

from apps.connections.models import Connection, Status
from apps.contacts.normalize import codes_for
from apps.keyring.phones import normalize
from apps.tenancy.scope import all_clients, tenant

from .models import DialerListEntry

PAGE = 1000
USABLE = [Status.CONNECTED, Status.STALE]


def save(client, source: str, lead_id, list_id, added_at, number: str) -> bool:
    e164 = normalize(str(number or ''))
    if not e164 or added_at is None:
        return False
    try:
        with transaction.atomic():
            DialerListEntry.objects.create(client=client, source_system=source, lead_id=str(lead_id), list_id=str(list_id or ''),
                                           added_at=added_at, phone_token=codes_for(client).token(e164))
        return True
    except IntegrityError:
        return False  # already read


def read_vicidial(connection) -> int:
    from apps.sync.connectors.vicidial import Vicidial
    tool = Vicidial(connection)
    after = (DialerListEntry.objects.filter(client=connection.client, source_system='vicidial')
             .aggregate(m=Max(Cast('lead_id', BigIntegerField())))['m'] or 0)  # Vicidial lead IDs only grow
    rows = tool.query('SELECT lead_id, list_id, entry_date, phone_number FROM vicidial_list WHERE lead_id > %s ORDER BY lead_id LIMIT %s',
                      (after, PAGE))
    tz = tool_zone(connection)
    return sum(save(connection.client, 'vicidial', r['lead_id'], r['list_id'], local(r.get('entry_date'), tz), r.get('phone_number')) for r in rows)


def read_convoso(connection) -> int:
    from apps.sync.connectors.convoso import WHEN, Convoso
    tool = Convoso(connection)
    newest = DialerListEntry.objects.filter(client=connection.client, source_system='convoso').aggregate(m=Max('added_at'))['m']
    start = (newest or datetime.combine(connection.client.start_date, datetime.min.time(), tzinfo=UTC)) - timedelta(seconds=1)
    data = tool._get('leads/search', {'created_at_start': start.astimezone(tool.tz).strftime(WHEN), 'limit': PAGE, 'offset': 0})
    rows = data.get('entries') or data.get('results') or []
    count = 0
    for r in rows:
        made = r.get('created_at') or r.get('date_created') or r.get('entry_date')
        at = datetime.strptime(str(made), WHEN).replace(tzinfo=tool.tz).astimezone(UTC) if made else None
        count += save(connection.client, 'convoso', r.get('id') or r.get('lead_id'), r.get('list_id'), at, r.get('phone_number'))
    return count


def tool_zone(connection):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(connection.get_credentials().get('time_zone') or 'America/New_York')
    except Exception:
        return ZoneInfo('America/New_York')


def local(value, tz):
    """Vicidial stores server-local times without a zone (America/New_York unless set)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    return value.replace(tzinfo=tz).astimezone(UTC) if value.tzinfo is None else value


READERS = {'vicidial': read_vicidial, 'convoso': read_convoso}


def read_all() -> int:
    with all_clients():
        connections = list(Connection.objects.filter(provider__in=READERS, status__in=USABLE).select_related('client'))
    total = 0
    for connection in connections:
        with tenant(connection.client):
            try:
                total += READERS[connection.provider](connection)
            except Exception:  # the dialer is down or refused: tried again next time
                continue
    return total
