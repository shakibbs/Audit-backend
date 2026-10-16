"""The monthly check (spec §5b, M37): what CiV read against an independent total, per measure; the lowest available
ratio of calls / texts / vendor leads is M37. A measure without an independent total is "not available" and left out,
never failed. days_present and stop_replies can flag the month but are not part of M37."""
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.connections.models import Connection, Status
from apps.contacts.models import ContactEvent
from apps.optouts.models import OptOutEvent
from apps.rulebook.business_days import BusinessCalendar
from apps.rulebook.lookup import NoRulebook, RuleSet
from apps.tenancy.scope import all_clients, tenant

from . import billing
from .models import PeriodIntegrity, Reconciliation

M37_MEASURES = ('calls', 'texts', 'vendor_leads')
BILLED_TOOLS = {'twilio': ('texts', 'calls')}  # tools with a billing API, and what they bill
USABLE = [Status.CONNECTED, Status.STALE]


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
        for measure in M37_MEASURES:
            sources = [p for p, measures in BILLED_TOOLS.items() if measure in measures and p in tools]
            if not sources:
                rows.append(_row(client, period, measure, available=False, note='No billing source connected by API'))
                continue
            for source in sources:
                channel = 'text' if measure == 'texts' else 'call'
                read = contacts.filter(source_system=source, channel=channel, direction='outbound').count()
                try:
                    billed = billing.twilio_billed(tools[source], measure, start, end) if start <= end else 0
                except Exception as error:  # the bill could not be read this time
                    rows.append(_row(client, period, measure, source, records=read, available=False, note=f'Bill not read: {type(error).__name__}'))
                    continue
                ratio = read / billed if billed else None
                note = 'Above 100%: listed for review' if ratio and ratio > 1 else ''
                rows.append(_row(client, period, measure, source, records=read, independent_total=billed, ratio=ratio,
                                 available=billed > 0, flagged=ratio is not None and ratio < floor, note=note or ('' if billed else 'Nothing billed')))
        if tools and start <= end:
            calendar = BusinessCalendar(RuleSet()) if _has_rulebook() else None
            working = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            working = [d for d in working if calendar is None or calendar.is_business_day(d)]
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
