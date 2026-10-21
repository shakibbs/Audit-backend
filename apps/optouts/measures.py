"""Module 9 step 5 (owner decision 2026-10-21: no paid test lines): M08 and M09 measured from the client's REAL
opt-outs, every day, from the tool checks of step 3. Evidence: the client's own tools (Tier 3), labelled "measured from
your real opt-outs". Only opt-outs that count (AI exam passed, or not AI) are used.
- M08 Opt-out propagation time: hours from the opt-out until every tool CiV can check had marked the number (median
  and 90th percentile; "never" when a tool still had not by the deadline). CiV checks 10 minutes after, then hourly,
  so times are accurate to about an hour.
- M09 Opt-outs unprocessed at deadline (deadline passed only): M09a not marked in some tool · M09b contacted after."""
from statistics import median

from django.utils import timezone

from apps.contacts.models import ContactEvent
from apps.rulebook.lookup import NoRulebook, RuleSet

from .marks import deadline_of
from .models import OptOutEvent

NEVER = float('inf')
SOURCE = 'Measured from your real opt-outs'


def _optouts(client, start, end):
    return OptOutEvent.objects.filter(client=client, counts=True, at__gte=start, at__lt=end).prefetch_related('mark_checks')


def hours_to_mark(event, now) -> float | None:
    """None = no tool could say (or the first check has not run); NEVER = a tool had not marked it by the deadline."""
    checks = [c for c in event.mark_checks.all() if c.marked is not None or c.marked_at]
    if not checks:
        return None
    if any(c.marked_at is None for c in checks):
        past = any(c.deadline_at and c.deadline_at <= now for c in checks)
        return NEVER if past else None  # still within the deadline: not decided yet
    return max((c.marked_at - event.at).total_seconds() for c in checks) / 3600


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]


def _show(hours: float) -> str:
    return 'NEVER' if hours == NEVER else f'{hours:.1f} h'


def propagation_time(client, start, end, now=None) -> dict:
    now = now or timezone.now()
    times = [h for h in (hours_to_mark(e, now) for e in _optouts(client, start, end)) if h is not None]
    if not times:
        return {'code': 'M08', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No opt-out checked in your tools yet',
                'source': SOURCE}
    mid = median(times)
    return {'code': 'M08', 'value': None if mid == NEVER else round(mid, 1), 'display': _show(mid),
            'note': f'Median of {len(times)} opt-out{"" if len(times) == 1 else "s"}; 90th percentile {_show(_p90(times))}',
            'notMeasured': None, 'source': SOURCE}


def unprocessed(client, start, end, now=None) -> dict:
    now = now or timezone.now()
    try:
        rules = RuleSet()
    except NoRulebook:
        rules = None
    done = not_marked = contacted = 0
    for event in _optouts(client, start, end):
        deadline = deadline_of(event, rules)
        if deadline is None or deadline > now:
            continue  # deadline not passed yet
        done += 1
        not_marked += any(c.missed for c in event.mark_checks.all())
        contacted += ContactEvent.objects.filter(client=client, phone_token=event.phone_token, is_primary=True, direction='outbound',
                                                 occurred_at__gt=deadline).exists()
    if not done:
        return {'code': 'M09', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No opt-out past its deadline yet',
                'source': SOURCE}
    return {'code': 'M09', 'value': None, 'display': f'{not_marked:,} · {contacted:,}', 'm09a': not_marked, 'm09b': contacted,
            'note': f'M09a not marked in a tool · M09b contacted after · of {done:,} opt-out{"" if done == 1 else "s"} past the deadline',
            'notMeasured': None, 'source': SOURCE}


WINDOW_DAYS = 90
BUCKETS = [('Under 1 h', 1), ('1–6 h', 6), ('6–24 h', 24), ('1–3 days', 72), ('Over 3 days', NEVER)]


def row_name(event) -> str:
    if event.method == 'keyword':
        return 'SMS reply — “STOP”'
    if event.method == 'crm_flag':
        return 'Ticked “do not call” in the CRM'
    return 'Spoken on a call' if event.channel == 'call' else 'SMS reply — plain words'


def tool_hours(check, event, now) -> float | None:
    if check.marked_at:
        return max(0.0, (check.marked_at - event.at).total_seconds() / 3600)
    if check.marked is False and check.deadline_at and check.deadline_at <= now:
        return NEVER
    return None


def revocation_page(client, now=None) -> dict:
    """The Revocation page's real numbers over the last 90 days. Before any opt-out is checked, the KPIs say "Not measured"
    and the matrix and chart keep their sample."""
    from datetime import timedelta

    from apps.rulebook.lookup import NoRulebook, RuleSet
    now = now or timezone.now()
    start = now - timedelta(days=WINDOW_DAYS)
    m08, m09 = propagation_time(client, start, now, now), unprocessed(client, start, now, now)
    times = [h for h in (hours_to_mark(e, now) for e in _optouts(client, start, now)) if h is not None]
    try:
        days = RuleSet().get('optout_deadline_business_days', on=now.date()).value
    except NoRulebook:
        days = 10
    out = {'windowDays': WINDOW_DAYS, 'tests': len(times), 'medianHours': m08['value'],
           'p90': None if not times else ('NEVER' if _p90(times) == NEVER else round(_p90(times), 1)),
           'notSuppressedByDeadline': m09.get('m09a', 0), 'contactedAfterDeadline': m09.get('m09b', 0), 'deadlineBusinessDays': days}
    if not times:
        return out
    tools = {}
    cells = {}
    for event in _optouts(client, start, now):
        for check in event.mark_checks.all():
            tools[check.connection_id] = check.connection
            hours = tool_hours(check, event, now)
            if hours is not None:
                cells.setdefault((row_name(event), check.connection_id), []).append(hours)
    order = sorted(tools.values(), key=lambda t: (t.kind == 'crm', t.tool.name))
    out['systems'] = [{'name': t.tool.name + (f' ({t.label})' if t.label else ''), 'contacting': t.kind != 'crm'} for t in order]
    out['rows'] = []
    for name in sorted({r for r, _ in cells}):
        row = []
        for t in order:
            found = cells.get((name, t.pk), [])
            mid = median(found) if found else None
            row.append({'hours': None if mid in (None, NEVER) else round(mid, 1), 'tested': bool(found), 'tests': len(found)})
        out['rows'].append({'channel': name, 'cells': row})
    low = 0
    out['distribution'] = []
    for label, high in BUCKETS:
        out['distribution'].append({'label': label, 'count': sum(1 for h in times if low <= h < high)})
        low = high
    out['distribution'].append({'label': 'Never', 'count': sum(1 for h in times if h == NEVER)})
    return out
