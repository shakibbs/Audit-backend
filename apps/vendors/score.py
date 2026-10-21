"""Module 12 step 2: Vendor score = clamp 0–100 of 100 × (1 − Σ wᵢ·rᵢ) with the Rulebook's vs_rate_weights; rates not
measured are left out and the weights re-normalised (the score says "partial: n of 6 rates measured", owner decision
2026-10-22). Grades from vs_grade_bands; under vs_min_leads_for_score leads → "not enough data". Saved nightly for
the current month; a drop of vs_alert_drop_points or more month on month raises an alert (Module 11)."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import VendorMonth
from .rates import RATES, setting, vendor_rates

WEIGHTS = [0.35, 0.30, 0.15, 0.10, 0.05, 0.05]
BANDS = {'A': 90, 'B': 80, 'C': 70, 'D': 60}


def score_of(rates: dict, on) -> float | None:
    weights = setting('vs_rate_weights', on) or WEIGHTS
    pairs = [(w, rates[k]) for w, (k, _) in zip(weights, RATES) if rates.get(k) is not None]
    if not pairs:
        return None
    penalty = sum(w * r for w, r in pairs) / sum(w for w, _ in pairs)
    return round(max(0.0, min(100.0, 100 * (1 - penalty))), 1)


def grade_of(score: float, on) -> str:
    bands = setting('vs_grade_bands', on) or BANDS
    return next((g for g in 'ABCD' if score >= bands[g]), 'F')


@transaction.atomic
def save_month(client, now=None) -> int:
    now = now or timezone.now()
    period = now.date().replace(day=1)
    minimum = int(setting('vs_min_leads_for_score', now.date()) or 100)
    VendorMonth.objects.filter(client=client, period=period).delete()
    rows = []
    for r in vendor_rates(client, now):
        enough = r['leads'] >= minimum
        score = score_of(r['rates'], now.date()) if enough else None
        rows.append(VendorMonth(client=client, period=period, key=r['key'], sub_id=r['subId'] or '', name=r['name'], leads=r['leads'],
                                rates=r['rates'], counts=r['counts'], measured=r['measured'], score=score,
                                grade=grade_of(score, now.date()) if score is not None else ''))
    VendorMonth.objects.bulk_create(rows)
    return len(rows)


def history(client, key: str, sub_id: str, period, months: int = 6) -> list:
    found = {v.period: v.score for v in VendorMonth.objects.filter(client=client, key=key, sub_id=sub_id)}
    out, current = [], period
    for _ in range(months):
        out.insert(0, found.get(current))
        current = (current - timedelta(days=1)).replace(day=1)
    return out


def drops(client, now=None) -> list[dict]:
    """Vendors (and sub-IDs) whose score fell by vs_alert_drop_points or more since last month."""
    now = now or timezone.now()
    period = now.date().replace(day=1)
    before = (period - timedelta(days=1)).replace(day=1)
    limit = float(setting('vs_alert_drop_points', now.date()) or 10)
    last = {(v.key, v.sub_id): v.score for v in VendorMonth.objects.filter(client=client, period=before, score__isnull=False)}
    out = []
    for v in VendorMonth.objects.filter(client=client, period=period, score__isnull=False):
        was = last.get((v.key, v.sub_id))
        if was is not None and was - v.score >= limit:
            out.append({'key': v.key, 'subId': v.sub_id, 'name': v.name, 'from': was, 'to': v.score, 'drop': round(was - v.score, 1)})
    return out


def grade_mix(client, now=None) -> dict:
    """M29: vendors at each grade this month (vendor rows, not sub-IDs), the lowest named."""
    period = (now or timezone.now()).date().replace(day=1)
    rows = list(VendorMonth.objects.filter(client=client, period=period, sub_id=''))
    scored = [v for v in rows if v.score is not None]
    if not rows:
        return {'code': 'M29', 'value': None, 'display': 'Not measured', 'note': '', 'notMeasured': 'No vendor named in your CRM records'}
    mix = {g: sum(v.grade == g for v in scored) for g in 'ABCDF'}
    lowest = min(scored, key=lambda v: v.score) if scored else None
    display = ' · '.join(f'{n} {g}' for g, n in mix.items() if n) or 'Not enough data'
    note = (f'Lowest: {lowest.name} ({lowest.score:.1f})' if lowest else '') + (f' · {len(rows) - len(scored)} with not enough data' if len(rows) > len(scored) else '')
    return {'code': 'M29', 'value': None, 'display': display, 'note': note.strip(' ·'), 'notMeasured': None}
