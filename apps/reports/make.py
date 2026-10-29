"""Making, keeping and deleting reports (Module 11 step 5)."""
import hashlib
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.access_log.recorder import record

from .models import Report
from .period import build, figures, text_of
from .words import banned_words

PERIOD = 'Period audit report'
KEEP = timedelta(days=4 * 365)


def make_period(client, period: date, by: str, request=None) -> Report:
    data = figures(client, period)
    bad = banned_words(text_of(data))
    if bad:
        report = Report.objects.create(client=client, name=PERIOD, period=period, status=Report.Status.BLOCKED, banned=bad, made_by=by)
        record('report_blocked', request=request, client_id=client.pk, object=f'{period:%b %Y} · {", ".join(bad)}'[:254])
        return report
    pdf, content_sha = build(data)
    report = Report(client=client, name=PERIOD, period=period, status=Report.Status.READY, made_by=by,
                    sha256=hashlib.sha256(pdf).hexdigest(), content_sha256=content_sha)
    report.file.save('report.pdf', ContentFile(pdf), save=False)
    report.save()
    record('report_made', request=request, client_id=client.pk, object=f'{PERIOD} {period:%b %Y} · sha256 {report.sha256}'[:254])
    return report


def latest_or_make(client, period: date, by: str, request=None) -> Report:
    found = Report.objects.filter(client=client, name=PERIOD, period=period, status=Report.Status.READY, purged_at__isnull=True).first()
    return found or make_period(client, period, by, request)


def last_month(today: date) -> date:
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def month_last_day(first: date) -> date:
    import calendar
    return first.replace(day=calendar.monthrange(first.year, first.month)[1])


def purge_old(now=None) -> int:
    now = now or timezone.now()
    n = 0
    from apps.evidence.holds import Holds
    holds = Holds()
    for report in Report.objects.filter(made_at__lt=now - KEEP, purged_at__isnull=True).exclude(file=''):
        month_end = month_last_day(report.period) if report.period else None
        if holds.covers(report.client_id, report.period or report.made_at, until=month_end) or holds.covers(report.client_id, report.made_at):
            continue  # under a legal hold (Module 14)
        report.file.delete(save=False)
        report.purged_at = now
        report.save(update_fields=['file', 'purged_at'])
        n += 1
    from .models import QuoteRequest
    for q in QuoteRequest.objects.filter(made_at__lt=now - KEEP).exclude(package=''):  # litigation packages: also 4 years
        if holds.covers(q.client_id, q.made_at):
            continue
        q.package.delete(save=False)
        q.save(update_fields=['package'])
        n += 1
    return n


RULEBOOK = 'Rulebook snapshot'


def make_rulebook(client, period: date, by: str, request=None) -> Report:
    """The Rulebook snapshot (Module 2) kept in the history like the audit report, so it can be downloaded again."""
    from apps.rulebook.snapshot import snapshot_pdf
    pdf = snapshot_pdf(client.name, period.strftime('%Y-%m'))
    report = Report(client=client, name=RULEBOOK, period=period, status=Report.Status.READY, made_by=by, sha256=hashlib.sha256(pdf).hexdigest())
    report.file.save('rulebook.pdf', ContentFile(pdf), save=False)
    report.save()
    record('report_made', request=request, client_id=client.pk, object=f'{RULEBOOK} {period:%b %Y} · sha256 {report.sha256}'[:254])
    return report


METRICS = 'Metric export'


def make_metrics(client, period: date, by: str, request=None) -> Report:
    """The month's saved metrics as a CSV: value, what is shown, its state (measured / not yet measured / worst case /
    rule pending), its 0–100 score and its note. Not yet saved → every row "not measured"."""
    import csv
    import io

    from apps.scoring.snapshots import latest
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['metric', 'value', 'shown', 'state', 'score_0_100', 'note'])
    run = latest(client, period)
    for m in (run.metrics.all().order_by('code') if run else []):
        w.writerow([m.code, '' if m.value is None else m.value, m.display, m.get_state_display(), '' if m.score is None else m.score,
                    (m.data.get('note') or m.data.get('notMeasured') or '')])
    data = out.getvalue().encode()
    report = Report(client=client, name=METRICS, period=period, status=Report.Status.READY, made_by=by, sha256=hashlib.sha256(data).hexdigest())
    report.file.save('metrics.csv', ContentFile(data), save=False)
    report.save()
    record('report_made', request=request, client_id=client.pk, object=f'{METRICS} {period:%b %Y} · sha256 {report.sha256}'[:254])
    return report
