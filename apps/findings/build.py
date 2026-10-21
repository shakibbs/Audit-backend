"""Module 11 step 1: every night after the scores are saved, the latest saved month's metrics become findings.
Owner decisions 2026-10-21: a finding for every measured metric scored below 100 and every worst case (missing client
data); never for "not yet measured"; severity from catalog.py; up to five masked examples; ordered severity first,
then how many were affected. Updated in place; closes when no longer found, reopens when found again."""
from django.utils import timezone

from apps.metrics.conduct import span
from apps.scoring.models import SnapshotRun

from .catalog import MEASURED, SKIP, WORST, WORST_SEVERITY
from .examples import flagged
from .models import Finding

ORDER = {'High': 0, 'Medium': 1, 'Low': 2}


def plural(n: int, unit: str) -> str:
    return f'{n:,} {unit}' + ('' if n == 1 else 's')


def found_in(client, run: SnapshotRun) -> dict[str, dict]:
    start, end = span(run.period.strftime('%Y-%m'))
    out = {}
    for m in run.metrics.all():
        if m.code in SKIP:
            continue
        if m.state == 'worst_case' and m.code in WORST:
            title, domain, why = WORST[m.code]
            out[f'{m.code}-worst'] = {'metric': m.code, 'title': title, 'severity': WORST_SEVERITY, 'domain': domain, 'why': why,
                                      'affected': 0, 'numbers': None, 'examples': []}
        elif m.state == 'measured' and m.score is not None and m.score < 100 and m.code in MEASURED:
            title, severity, domain, unit = MEASURED[m.code]
            examples, numbers = flagged(client, m.code, start, end)
            count = int(m.value) if isinstance(m.value, (int, float)) and unit else 0
            what = plural(count, unit) if unit else m.display
            why = f'CiV found {what}' + (f' ({plural(numbers, "number")})' if numbers else '') + f' in {run.period:%B %Y}.'
            if m.data.get('note'):
                why += f' {m.data["note"]}'
            out[m.code] = {'metric': m.code, 'title': title, 'severity': severity, 'domain': domain, 'why': why[:400],
                           'affected': count, 'numbers': numbers, 'examples': examples}
    return out


def refresh(client, now=None) -> int:
    """Update this client's findings from its latest saved month. Returns how many are open."""
    now = now or timezone.now()
    run = SnapshotRun.objects.filter(client=client).order_by('-period', '-version').first()
    if run is None:
        return 0
    found = found_in(client, run)
    for key, f in found.items():
        row = Finding.objects.filter(client=client, key=key).first()
        if row is None:
            Finding.objects.create(client=client, key=key, period=run.period, first_seen=now, last_seen=now, **f)
            continue
        for k, v in f.items():
            setattr(row, k, v)
        row.period, row.last_seen = run.period, now
        if row.status == Finding.Status.RESOLVED:
            row.status, row.resolved_at = Finding.Status.REOPENED, None
        row.save()
    Finding.objects.filter(client=client).exclude(key__in=found).exclude(status=Finding.Status.RESOLVED) \
        .update(status=Finding.Status.RESOLVED, resolved_at=now)
    return Finding.objects.filter(client=client).exclude(status=Finding.Status.RESOLVED).count()


def ranked(client) -> list[Finding]:
    rows = list(Finding.objects.filter(client=client))
    return sorted(rows, key=lambda f: (f.status == Finding.Status.RESOLVED, ORDER[f.severity], -f.affected, f.title))
