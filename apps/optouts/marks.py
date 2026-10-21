"""Module 9 step 3: after each opt-out, did the client's tools mark the number "do not contact"?
One small check per tool, everything else shared:
- dialers: the number is re-read from the tool's own call record (in memory, never stored) and looked up in the tool's
  do-not-call list — Vicidial vicidial_dnc / vicidial_campaign_dnc; Convoso DNC search (to confirm); Five9 later;
- texting: Twilio blocks a number itself after a STOP word; plain-word opt-outs can't be checked there;
- CRMs: the record's opt-out / do-not-call field as last synced (no extra calls).
Timing: first check 10 minutes after (the run is every 5 minutes, so urgent within 15) CiV learned of the opt-out; not marked → urgent. Not marked (or not checked) →
checked again every hour until the deadline; marked → checked once more a day later. Deadline passed, not marked →
missed (M38)."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.connections.providers import Kind
from apps.contacts.models import ContactEvent
from apps.contacts.normalize import codes_for
from apps.imports.models import CrmCreation
from apps.keyring.phones import normalize
from apps.rulebook.business_days import optout_deadline, pick_time_zone
from apps.rulebook.lookup import NoRulebook, RuleSet

from .models import MarkCheck, OptOutEvent

GRACE = timedelta(minutes=10)  # with the 5-minute run: urgent within 15 minutes
AGAIN = timedelta(hours=1)
DAY = timedelta(days=1)
NEW = timedelta(days=1)  # older opt-outs (e.g. at first sync) are checked, but raise no urgent alert
USABLE = [Status.CONNECTED, Status.STALE]
KINDS = [Kind.DIALER, Kind.SMS, Kind.CRM]


class NotChecked(Exception):
    """The tool can't tell CiV whether the number is marked."""


def number_from(client, contact: ContactEvent | None, read) -> str:
    """The number, re-read from the tool's own record and checked against the phone code (in memory only)."""
    if contact is None:
        raise NotChecked('No call from this tool to re-read the number from')
    number = normalize(read(contact.source_record_id) or '')
    if number is None or codes_for(client).token(number) != contact.phone_token:
        raise NotChecked('The tool did not give back the same number')
    return number


def vicidial(client, connection, event, contact) -> bool:
    from apps.sync.connectors.vicidial import TABLES, Vicidial
    tool = Vicidial(connection)
    tables = {t.name: t for t in TABLES}

    def read(record_id):
        name, _, key = record_id.partition(':')
        table = tables.get(name)
        if table is None:
            return None
        rows = tool.query(f'SELECT phone_code, phone_number FROM {table.table} WHERE {table.id_column} = %s LIMIT 1', (key,))
        return f"{rows[0].get('phone_code') or ''}{rows[0].get('phone_number') or ''}" if rows else None

    number = number_from(client, contact, read)
    local = number[-10:]
    rows = tool.query('SELECT phone_number FROM vicidial_dnc WHERE phone_number IN (%s, %s) '
                      'UNION ALL SELECT phone_number FROM vicidial_campaign_dnc WHERE phone_number IN (%s, %s) LIMIT 1',
                      (local, number.lstrip('+'), local, number.lstrip('+')))
    return bool(rows)


def convoso(client, connection, event, contact) -> bool:
    """TO CONFIRM on a real account: DNC search by phone number."""
    from apps.sync.connectors.convoso import Convoso
    tool = Convoso(connection)

    def read(record_id):
        rows = tool._get('log/retrieve', {'id': record_id, 'limit': 1, 'offset': 0}).get('results') or []
        return rows[0].get('phone_number') if rows else None

    number = number_from(client, contact, read)
    found = tool._get('dnc/search', {'phone_number': number[-10:]})
    return bool(found.get('results') or found.get('data'))


def twilio(client, connection, event, contact) -> bool:
    if event.method == OptOutEvent.Method.KEYWORD and event.source_system == 'twilio':
        return True  # Twilio itself blocks texts to a number that replied with a stop word
    raise NotChecked('Twilio has no do-not-text list CiV can read for plain-word opt-outs')


def crm(client, connection, event, contact) -> bool:
    records = CrmCreation.objects.filter(client=client, source_system=connection.provider, phone_tokens__contains=[event.phone_token])
    if not records.exists():
        raise NotChecked('No CRM record with this number')
    if records.filter(opted_out=True).exists() or OptOutEvent.objects.filter(
            client=client, phone_token=event.phone_token, method=OptOutEvent.Method.CRM_FLAG, source_system=connection.provider).exists():
        return True
    if records.filter(opted_out=False).exists():
        return False
    raise NotChecked("The CRM record has no opt-out or do-not-call field")


CHECKS = {'vicidial': vicidial, 'convoso': convoso, 'twilio': twilio, 'salesforce': crm, 'hubspot': crm}  # Five9: later


def check(client, connection, event) -> tuple[bool | None, str]:
    found = CHECKS.get(connection.provider)
    if found is None:
        return None, "CiV can't check this tool yet"
    contact = (ContactEvent.objects.filter(client=client, phone_token=event.phone_token, source_system=connection.provider)
               .order_by('-occurred_at').first())
    try:
        return found(client, connection, event, contact), ''
    except NotChecked as why:
        return None, str(why)
    except Exception as error:  # tool down or refused: not checked this time
        return None, f'The tool did not answer ({type(error).__name__})'


def deadline_of(event, rules) -> datetime | None:
    if rules is None:
        return None
    latest = ContactEvent.objects.filter(client_id=event.client_id, phone_token=event.phone_token).order_by('-occurred_at').first()
    zone = pick_time_zone(None, (latest.time_zones or [None])[0] if latest and latest.time_zones else None,
                          ['recipient_zip', 'area_code', 'America/New_York'])
    return datetime.combine(optout_deadline(event.at, time_zone=zone, rules=rules).date, time.max, tzinfo=ZoneInfo(zone))


def record(row: MarkCheck, marked: bool | None, note: str, now) -> None:
    row.marked, row.note, row.checked_at = marked, note, now
    if marked and row.marked_at is None:
        row.marked_at = now


def run(client, now=None) -> int:
    """One pass for one client. Returns how many checks were made."""
    now = now or timezone.now()
    try:
        rules = RuleSet()
    except NoRulebook:
        rules = None
    tools = list(Connection.objects.filter(client=client, kind__in=KINDS, status__in=USABLE))
    done = 0
    # 1. First check, 15 minutes after CiV learned of the opt-out.
    events = (OptOutEvent.objects.filter(client=client, lifted_at__isnull=True, created_at__lte=now - GRACE)
              .annotate(n=Count('mark_checks')).filter(n__lt=len(tools)))
    for event in events:
        have = set(event.mark_checks.values_list('connection_id', flat=True))
        for tool in (t for t in tools if t.pk not in have):
            marked, note = check(client, tool, event)
            row = MarkCheck(client=client, optout=event, connection=tool, deadline_at=deadline_of(event, rules), checked_at=now)
            record(row, marked, note, now)
            if marked is False and event.created_at >= now - NEW:
                row.urgent_at = now
            row.save()
            done += 1
    # 2. Not marked or not checked: again every hour until the deadline. Marked: once more a day later.
    open_rows = MarkCheck.objects.filter(client=client, missed=False, optout__lifted_at__isnull=True).select_related('optout', 'connection')
    for row in open_rows:
        before = row.marked
        past = row.deadline_at is not None and row.deadline_at <= now
        if past and row.checked_at >= row.deadline_at:
            continue  # final: checked after the deadline
        if row.marked:
            if row.day_check_done or row.marked_at > now - DAY:
                continue
            row.day_check_done = True
        elif row.checked_at > now - AGAIN and not past:
            continue
        marked, note = check(client, row.connection, row.optout)
        record(row, marked, note, now)
        if before and marked is False and row.urgent_at is None:
            row.urgent_at = now  # was marked, now unmarked
        if marked is False and past:
            row.missed = True
        row.save()
        done += 1
    return done


def missed_optouts(client, start, end) -> dict:
    """M38 Missed opt-outs: opt-outs in the period still not marked in some tool at their deadline."""
    rows = MarkCheck.objects.filter(client=client, optout__at__gte=start, optout__at__lt=end, optout__counts=True)
    if not rows.exclude(marked__isnull=True).exists():
        return {'code': 'M38', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No opt-out checked in your tools yet'}
    n = rows.filter(missed=True).values('optout').distinct().count()
    return {'code': 'M38', 'value': n, 'display': f'{n:,}', 'note': 'Opt-outs not marked in every tool by the deadline', 'notMeasured': None}
