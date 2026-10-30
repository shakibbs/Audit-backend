"""Module 12 step 5: the Vendor Ledger from the real scorecards — every vendor and sub-ID with its score, grade, month
on month change, 6-month trend, drop alert, the rates behind the score (high-risk signals and name match "not measured
yet"), contract and dispute candidates; and the page's cards (M29 grade mix, dispute candidates, score-drop alerts).
This month's saved rows are used; before the first nightly save they are worked out on the spot (not saved)."""
from datetime import timedelta

from django.utils import timezone

from apps.provenance.api import vendor_id

from .api import contract_row
from .contracts import latest, state
from .disputes import candidates
from .models import VendorMonth
from .rates import NOT_YET, RATES, setting, vendor_rates
from .score import drops, grade_mix, grade_of, history, score_of


def current_rows(client, now) -> list[dict]:
    period = now.date().replace(day=1)
    saved = list(VendorMonth.objects.filter(client=client, period=period))
    if saved:
        return [{'key': v.key, 'subId': v.sub_id, 'name': v.name, 'leads': v.leads, 'rates': v.rates, 'measured': v.measured,
                 'score': v.score, 'grade': v.grade} for v in saved]
    minimum = int(setting('vs_min_leads_for_score', now.date()) or 100)
    out = []
    for r in vendor_rates(client, now):
        score = score_of(r['rates'], now.date()) if r['leads'] >= minimum else None
        out.append({**r, 'subId': r['subId'] or '', 'score': score, 'grade': grade_of(score, now.date()) if score is not None else ''})
    return out


def vendors_page(client, now=None, period: str | None = None) -> dict:
    """The Vendor Ledger as of now, or as of the end of the month picker's month (owner, 2026-10-30)."""
    from datetime import UTC, datetime, time

    from apps.refs import month_span
    now = now or timezone.now()
    span = month_span(period)
    if span:
        now = min(now, datetime.combine(span[1], time.min, tzinfo=UTC) - timedelta(seconds=1))
    when = f'in {span[0]:%b %Y}' if span else 'this month'
    rows = current_rows(client, now)
    if not rows:  # no vendor yet: say so (owner decision 2026-10-22: a real client never sees the sample vendors)
        return {'gradeMix': 'Not measured', 'gradeMixNote': 'No vendor named in your CRM records or uploaded vendor lead files',
                'disputeCandidates': 0, 'alerts': 0, 'alertNote': 'No vendors yet', 'vendors': []}
    period = now.date().replace(day=1)
    before = (period - timedelta(days=1)).replace(day=1)
    last = {(v.key, v.sub_id): v.score for v in VendorMonth.objects.filter(client=client, period=before, score__isnull=False)}
    dropped = {(d['key'], d['subId']) for d in drops(client, now)}
    disputes = candidates(client, now)
    labels = dict(RATES)
    out = []
    for r in sorted(rows, key=lambda r: (r['key'], r['subId'] != '', r['subId'])):
        key, sub = r['key'], r['subId']
        contract = latest(client, key)
        was = last.get((key, sub))
        out.append({
            'id': vendor_id(f'{key}|{sub}'), 'name': r['name'], 'subId': sub or None, 'leads': r['leads'], 'highSignals': None,
            'score': r['score'], 'grade': r['grade'] or None, 'notEnoughData': r['score'] is None,
            'monthOnMonth': round(r['score'] - was, 1) if r['score'] is not None and was is not None else None,
            'alert': (key, sub) in dropped, 'history': history(client, key, sub, period),
            'termsOnFile': state(contract, now.date()) == 'on_file', 'contract': contract_row(contract) if contract else None,
            'disputeCandidates': len([x for x in disputes.get(key, {}).get('rows', []) if not sub or x['subId'] == sub]),
            'rates': [{'label': labels[k], 'value': round(100 * v, 1)} for k, v in r['rates'].items() if v is not None],
            'notMeasuredRates': [label for k, label in RATES if k in NOT_YET], 'ratesMeasured': r['measured'], 'ratesTotal': len(RATES),
        })
    mix = grade_mix(client, now)
    total_disputes = sum(len(v['rows']) for v in disputes.values())
    n_drops = len(dropped)
    return {'gradeMix': mix['display'] if not mix['notMeasured'] else 'Not measured', 'gradeMixNote': mix.get('note') or mix.get('notMeasured') or '',
            'disputeCandidates': total_disputes, 'alerts': n_drops,
            'alertNote': f'{n_drops} vendor{"" if n_drops == 1 else "s"} fell 10 points or more {when}' if n_drops else f'No score fell 10 points or more {when}',
            'vendors': out}
