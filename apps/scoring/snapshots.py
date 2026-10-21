"""Module 10 step 1: every night, each client's metrics for every open month are counted and saved; locked months are
re-checked on Sundays and get a new, revised version only when something changed (never overwritten).
Owner decisions 2026-10-21: lock 5 days after the month ends; revisions kept; the month list runs from the client's
start date, newest first."""
import hashlib
import json
from datetime import date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.metrics.conduct import conduct_metrics, contacts as contacts_in, span
from apps.metrics.overview import overview_metrics
from apps.optouts.marks import missed_optouts

from .extra import extra_metrics
from .exposure import exposure
from .factors import factors
from .models import MetricSnapshot, SnapshotRun
from .scores import bands, score

LOCK_DAYS = 5
S = MetricSnapshot.State


def months(client, today: date | None = None) -> list[date]:
    """First days of every month from the client's start date to this one, newest first."""
    today = today or timezone.localdate()
    first, out = date(client.start_date.year, client.start_date.month, 1), []
    current = date(today.year, today.month, 1)
    while current >= first:
        out.append(current)
        current = (current - timedelta(days=1)).replace(day=1)
    return out


def lock_day(period: date) -> date:
    nxt = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt + timedelta(days=LOCK_DAYS)


def state_of(metric: dict) -> str:
    if metric.get('worstCase') or metric.get('worst_case'):
        return S.WORST_CASE
    if 'pending' in (metric.get('note') or '').lower() and metric.get('value') is None:
        return S.RULE_PENDING
    return S.NOT_MEASURED if metric.get('notMeasured') or (metric.get('value') is None and metric.get('display') == 'Not measured') else S.MEASURED


def measure(client, period: date) -> list[dict]:
    key = period.strftime('%Y-%m')
    start, end = span(key)
    sent = contacts_in(client, start, end)
    found = (conduct_metrics(client, key) + overview_metrics(client, key) + [missed_optouts(client, start, end)]
             + extra_metrics(client, start, end, sent))
    base, table = sent.count(), bands(period)
    for metric in found:
        metric.pop('history', None)  # history comes from the saved months
        metric['score'] = score(metric, state_of(metric), base, table)  # step 2 (a band change shows up as a change too)
    return found


def fingerprint(metrics: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted(metrics, key=lambda m: m['code']), sort_keys=True, default=str).encode()).hexdigest()


def latest(client, period: date) -> SnapshotRun | None:
    return SnapshotRun.objects.filter(client=client, period=period).order_by('-version').first()


def scored(client, period: date, metrics: list[dict]) -> dict:
    """Steps 3–4: the factors, D, and the Exposure with its multipliers, grade and caps."""
    start, end = span(period.strftime('%Y-%m'))
    result = factors(metrics)
    result['exposure'] = exposure(client, start, end, contacts_in(client, start, end), result['defect'], period)
    return result


@transaction.atomic
def save(client, period: date, metrics: list[dict], run: SnapshotRun | None, now: datetime, locked: bool, revised: bool) -> SnapshotRun:
    base = contacts_in(client, *span(period.strftime('%Y-%m'))).count()
    if run is None:
        version = (latest(client, period).version + 1) if latest(client, period) else 1
        run = SnapshotRun.objects.create(client=client, period=period, version=version, ran_at=now, locked=locked, revised=revised,
                                         fingerprint=fingerprint(metrics), contacts=base,
                                         score=scored(client, period, metrics))
    else:
        run.ran_at, run.locked, run.fingerprint, run.contacts = now, locked, fingerprint(metrics), base
        run.score = scored(client, period, metrics)
        run.save()
        run.metrics.all().delete()
    MetricSnapshot.objects.bulk_create([MetricSnapshot(client=client, run=run, code=m['code'], value=m.get('value'), display=str(m.get('display') or '')[:80],
                                                       state=state_of(m), score=m['score'], data=json.loads(json.dumps(m, default=str))) for m in metrics])
    return run


def snapshot(client, period: date, now: datetime | None = None, recheck_locked: bool = False) -> SnapshotRun | None:
    """Open month: count and save (replacing the open copy). Locked month: only on a re-check, and only a new version
    when the results changed. Returns the run saved, or None when nothing was saved."""
    now = now or timezone.now()
    run = latest(client, period)
    locked = now.date() >= lock_day(period)
    if run and run.locked:
        if not recheck_locked:
            return None
        metrics = measure(client, period)
        return None if fingerprint(metrics) == run.fingerprint else save(client, period, metrics, None, now, True, True)
    return save(client, period, measure(client, period), run, now, locked, False)


def run_nightly(client, now: datetime | None = None) -> int:
    """Open months every night (and any month never saved); locked months re-checked on Sundays."""
    now = now or timezone.now()
    sunday = now.weekday() == 6
    return sum(snapshot(client, p, now, recheck_locked=sunday) is not None for p in months(client, now.date()))


def saved_metrics(client, key: str) -> list[dict] | None:
    """The saved metrics of a month with a four-month history from the saved months, or None when not saved yet."""
    period = datetime.strptime(key, '%Y-%m').date()
    run = latest(client, period)
    if run is None:
        return None
    earlier = [latest(client, p) for p in months_back(period, 3)]
    past = [{m.code: m.value for m in r.metrics.all()} if r else {} for r in earlier]
    out = []
    for m in run.metrics.all().order_by('code'):
        out.append({**m.data, 'history': [p.get(m.code) for p in past] + [m.value],
                    **({'revisedOn': run.ran_at.date().isoformat()} if run.revised else {})})
    return out


def months_back(period: date, n: int) -> list[date]:
    out, current = [], period
    for _ in range(n):
        current = (current - timedelta(days=1)).replace(day=1)
        out.insert(0, current)
    return out


def periods(client) -> list[dict]:
    """The month picker: every month since the client's start date, newest first; a revised month says so."""
    out = []
    for p in months(client):
        run = latest(client, p)
        item = {'id': p.strftime('%Y-%m'), 'label': p.strftime('%b %Y')}
        if run and run.revised:
            item['revisedOn'] = run.ran_at.date().isoformat()
        out.append(item)
    return out
