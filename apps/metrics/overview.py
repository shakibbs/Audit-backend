"""Overview key numbers that are real now: M01 consent coverage and M10 contacts after opt-out, from the consent
engine's strict results (pending, frozen and "not needed" left out), and M08 / M09 from real opt-outs (Module 9),
with a four-month history."""
from apps.consent.models import ConsentResult

from .conduct import months_before, span


def _results(client, start, end):
    return (ConsentResult.objects.filter(client=client, variant='strict', frozen=False, contact__is_primary=True,
                                         contact__occurred_at__gte=start, contact__occurred_at__lt=end)
            .exclude(status__in=['pending', 'not_needed']))


def coverage(client, start, end) -> dict:
    rows = _results(client, start, end)
    legal = rows.filter(is_legal_basis=True)
    if not rows.exists():
        return {'code': 'M01', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No checked contacts in the period'}
    covered = legal.filter(status__in=['verified', 'weak']).count()
    all_covered = rows.filter(status__in=['verified', 'weak']).count()
    value = round(100 * covered / legal.count(), 1) if legal.exists() else None
    overall = round(100 * all_covered / rows.count(), 1)
    return {'code': 'M01', 'value': value, 'display': f'{value}%' if value is not None else '—',
            'note': f'Legal-basis contacts covered; {overall}% including CiV-policy contacts', 'notMeasured': None,
            'evidence': f'{covered:,} of {legal.count():,} legal-basis contacts'}


def after_optout(client, start, end) -> dict:
    rows = _results(client, start, end).filter(codes__contains=['NP_AFTER_OPT_OUT'])
    n = rows.count()
    numbers = rows.values('contact__phone_token').distinct().count()
    return {'code': 'M10', 'value': n, 'display': f'{n:,}', 'note': f'{numbers:,} number{"" if numbers == 1 else "s"} affected', 'notMeasured': None}


def overview_metrics(client, period) -> list[dict]:
    from apps.optouts.measures import propagation_time, unprocessed
    out = []
    for fn in (coverage, after_optout, propagation_time, unprocessed):
        now = fn(client, *span(period))
        now['history'] = [fn(client, *span(p))['value'] for p in months_before(period, 3)] + [now['value']]
        out.append(now)
    return out
