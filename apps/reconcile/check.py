"""The monthly check (spec §5b, M37): for every connected tool, what CiV read against a second number, found the best
way the tool allows:
1. bill: the tool's billing (Twilio) — CiV saw everything the client paid for;
2. tool_total: the tool's own count, asked in one request — CiV read everything the tool has;
3. volume: no bill and no total (or it could not be read) — working days with records, and no sudden drop.
The lowest available ratio over all tools is M37. "Not available" is left out, never failed. days_present (all
tools together) and stop_replies can flag the month but are not part of M37."""
from datetime import UTC, date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation
from apps.optouts.models import OptOutEvent
from apps.rulebook.business_days import BusinessCalendar
from apps.rulebook.lookup import NoRulebook, RuleSet
from apps.sync.connector import connector_for
from apps.tenancy.scope import all_clients, tenant

from . import billing
from .models import PeriodIntegrity, Reconciliation

M37_MEASURES = ('calls', 'texts', 'vendor_leads', 'crm_records')
BILLED_TOOLS = {'twilio': ('texts', 'calls')}  # tools with a billing API, and what they bill
USABLE = [Status.CONNECTED, Status.STALE]
MAIN_MEASURE = {'twilio': 'texts', 'salesforce': 'crm_records', 'hubspot': 'crm_records'}  # volume check; others: calls
DROP_SHARE = 0.25  # last 7 days' daily average below a quarter of the 4 weeks before = a sudden drop
Method = Reconciliation.Method


def month_bounds(period: date) -> tuple[date, date]:
    end = (period.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return period, end


def rule(key: str, default):
    try:
        return RuleSet().get(key, on=timezone.localdate()).value or default
    except NoRulebook:
        return default


def _row(client, period, measure, source='', **fields) -> Reconciliation:
    row, _ = Reconciliation.objects.update_or_create(client=client, period=period, measure=measure, source_system=source, defaults=fields)
    return row


def check_month(client, period: date) -> PeriodIntegrity:
    floor = rule('completeness_floor', 0.9)
    start, end = month_bounds(period)
    end = min(end, timezone.localdate() - timedelta(days=1))  # today is not over yet
    start = max(start, client.start_date)
    contacts = ContactEvent.objects.filter(client=client, occurred_at__date__gte=start, occurred_at__date__lte=end)
    rows: list[Reconciliation] = []
    with tenant(client), transaction.atomic():
        Reconciliation.objects.filter(client=client, period=period).delete()
        tools = {c.provider: c for c in Connection.objects.filter(client=client, status__in=USABLE)}
        working = working_days(start, end)
        for provider, conn in sorted(tools.items()):
            done = set()
            for measure in BILLED_TOOLS.get(provider, ()):
                rows.append(by_bill(client, period, conn, measure, contacts, start, end, floor))
                done.add(measure)
            reader = connector_for(conn)
            for measure in [m for m in (reader.counts if reader else ()) if m not in done]:
                rows.append(by_tool_total(client, period, reader, measure, contacts, start, end, floor, working))
                done.add(measure)
            if not done:
                rows.append(by_volume(client, period, provider, MAIN_MEASURE.get(provider, 'calls'), contacts, start, end, floor, working,
                                      note='' if reader else 'CiV cannot read this tool yet'))
        if tools and start <= end:
            present = set(contacts.values_list('occurred_at__date', flat=True).distinct())
            seen = sum(1 for d in working if d in present)
            ratio = seen / len(working) if working else None
            rows.append(_row(client, period, 'days_present', records=seen, independent_total=len(working), ratio=ratio,
                             available=bool(working), flagged=ratio is not None and ratio < floor))
            sent = contacts.filter(channel='text', direction='outbound').count()
            stops = OptOutEvent.objects.filter(client=client, method=OptOutEvent.Method.KEYWORD, at__date__gte=start, at__date__lte=end).count()
            limit = rule('stop_check_min_texts', 1000)
            rows.append(_row(client, period, 'stop_replies', records=stops, independent_total=sent, flagged=sent > limit and stops == 0,
                             note=f'No STOP replies although {sent:,} texts were sent' if sent > limit and stops == 0 else ''))
        ratios = [r.ratio for r in rows if r.measure in M37_MEASURES and r.available and r.ratio is not None]
        completeness = min(ratios) if ratios else None
        integrity, _ = PeriodIntegrity.objects.update_or_create(client=client, period=period, defaults={
            'completeness': completeness, 'floor': floor, 'incomplete': completeness is not None and completeness < floor,
            'flagged_by': sorted({r.measure for r in rows if r.flagged}),
            'contacts': contacts.filter(is_primary=True).count()})
    return integrity


def working_days(start: date, end: date) -> list[date]:
    calendar = BusinessCalendar(RuleSet()) if _has_rulebook() else None
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return [d for d in days if calendar is None or calendar.is_business_day(d)]


def _span(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time(0), tzinfo=UTC), datetime.combine(end + timedelta(days=1), time(0), tzinfo=UTC)


def civ_read(client, provider: str, measure: str, contacts, start: date, end: date, outbound_only=False) -> int:
    """What CiV read from this tool: its calls or texts, or the CRM people and leads created."""
    if measure == 'crm_records':
        return CrmCreation.objects.filter(client=client, source_system=provider, created_at__date__gte=start, created_at__date__lte=end).count()
    found = contacts.filter(source_system=provider, channel='text' if measure == 'texts' else 'call')
    return found.filter(direction='outbound').count() if outbound_only else found.count()


def _compared(client, period, provider, measure, method, read, total, floor, note=''):
    ratio = read / total if total else None
    note = note or ('Above 100%: listed for review' if ratio and ratio > 1 else '' if total else 'Nothing in the tool for this month')
    return _row(client, period, measure, provider, method=method, records=read, independent_total=total, ratio=ratio,
                available=bool(total), flagged=ratio is not None and ratio < floor, note=note)


def by_bill(client, period, conn, measure, contacts, start, end, floor) -> Reconciliation:
    read = civ_read(client, conn.provider, measure, contacts, start, end, outbound_only=True)
    try:
        billed = billing.twilio_billed(conn, measure, start, end) if start <= end else 0
    except Exception as error:  # the bill could not be read this time
        return _row(client, period, measure, conn.provider, method=Method.BILL, records=read, available=False, note=f'Bill not read: {type(error).__name__}')
    return _compared(client, period, conn.provider, measure, Method.BILL, read, billed, floor, note='' if billed else 'Nothing billed')


def by_tool_total(client, period, reader, measure, contacts, start, end, floor, working) -> Reconciliation:
    provider = reader.connection.provider
    read = civ_read(client, provider, measure, contacts, start, end)
    try:
        total = reader.count_between(measure, *_span(start, end)) if start <= end else 0
    except Exception as error:  # the total could not be read this time: the volume pattern stands in
        return by_volume(client, period, provider, measure, contacts, start, end, floor, working, note=f'Total not read ({type(error).__name__}): checked by volume pattern instead')
    return _compared(client, period, provider, measure, Method.TOOL_TOTAL, read, total, floor)


def by_volume(client, period, provider, measure, contacts, start, end, floor, working, note='') -> Reconciliation:
    """Working days with records from this tool; and a sudden drop in the last 7 days against the 4 weeks before."""
    if measure == 'crm_records':
        dates = CrmCreation.objects.filter(client=client, source_system=provider, created_at__date__gte=start, created_at__date__lte=end).values_list('created_at__date', flat=True)
    else:
        dates = contacts.filter(source_system=provider).values_list('occurred_at__date', flat=True)
    present = set(dates)
    seen = sum(1 for d in working if d in present)
    ratio = seen / len(working) if working else None
    flagged = ratio is not None and ratio < floor
    recent = before = 0
    if measure != 'crm_records':
        recent = contacts.filter(source_system=provider, occurred_at__date__gt=end - timedelta(days=7)).count() / 7
        before = ContactEvent.objects.filter(client=client, source_system=provider, occurred_at__date__gt=end - timedelta(days=35),
                                             occurred_at__date__lte=end - timedelta(days=7)).count() / 28
    if before and recent < before * DROP_SHARE:
        flagged, note = True, note or f'Sudden drop: about {recent:,.0f} a day in the last 7 days, {before:,.0f} a day before'
    return _row(client, period, measure, provider, method=Method.VOLUME, records=seen, independent_total=len(working), ratio=ratio,
                available=bool(working) and not note.startswith('CiV cannot'), flagged=flagged, note=note)


def _has_rulebook() -> bool:
    try:
        RuleSet()
        return True
    except NoRulebook:
        return False


def check_recent() -> None:
    """Every night: this month and last month, for every client with a connected tool."""
    from apps.clients.models import Client
    today = timezone.localdate()
    this = today.replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    with all_clients():
        ids = set(Connection.objects.filter(status__in=USABLE).values_list('client_id', flat=True))
    for client in Client.objects.filter(pk__in=ids):
        for period in (last, this):
            check_month(client, period)
