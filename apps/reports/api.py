"""Client API (Module 11 step 5): GET /api/reports — the report types and the report history; POST /api/reports {name, period} — "Generate": the period audit report, the Rulebook snapshot and the metric export
are made now; the evidence file, certification pack and litigation package come with Module 14 (recorded as not
available yet); GET /api/reports/period?period=YYYY-MM — that month's report PDF (made if there is none yet);
GET /api/reports/rep-<id>/file — a past report. Every download is logged."""
from datetime import datetime

from django.http import FileResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .make import METRICS, PERIOD, RULEBOOK, latest_or_make, make_metrics, make_period, make_rulebook
from .models import Report
from apps.refs import number


# The Reports & Exports cards: id, name, what it holds, format, add-on.
TYPES = [
    ('period', PERIOD, 'Scorecard, domains, metrics and action queue for the selected month.', 'PDF', False),
    ('evidence', 'Evidence file export', 'Per phone number: every contact, its consent decision, proof elements, tiers and hashes. Made from the bulk export below.', 'PDF + JSON', False),
    ('certification', 'Certification pack', 'Hash manifest, capture description and custodian certification template. Made from the bulk export below.', 'ZIP', False),
    ('litigation', 'Litigation evidence package', 'Court-ready export for up to 25 named numbers with a chain-of-custody report.', 'Add-on', True),
    ('metrics', METRICS, 'Every measured metric with its value, note and data completeness.', 'CSV', False),
    ('rulebook', RULEBOOK, 'Every rule value in force for the period, with effective dates.', 'PDF', False),
]
NAMES = {name for _, name, _, _, _ in TYPES}


def types() -> list[dict]:
    return [{'id': i, 'name': n, 'description': d, 'format': f, 'addOn': a} for i, n, d, f, a in TYPES]


def allowed_month(client, period) -> bool:
    """From the client's first month to this one: no reports for months before CiV started or still to come."""
    from django.utils import timezone
    return client.start_date.replace(day=1) <= period <= timezone.localdate().replace(day=1)


def row(r: Report) -> dict:
    ready = r.status == Report.Status.READY and r.file and not r.purged_at
    return {'id': f'rep-{r.pk}', 'name': r.name, 'period': r.period.strftime('%b %Y') if r.period else '—', 'requestedBy': r.made_by,
            'at': r.made_at, 'status': 'ready' if ready else ('blocked' if r.status == Report.Status.BLOCKED else 'unavailable'),
            'url': f'/api/reports/rep-{r.pk}/file' if ready else None, 'sha256': r.sha256 or None}


def month_from(value: str):
    for fmt in ('%Y-%m', '%b %Y'):
        try:
            return datetime.strptime(value.strip(), fmt).date().replace(day=1)
        except (ValueError, AttributeError):
            continue
    return None


def send(request, r: Report):
    record('report_downloaded', request=request, actor_kind='client_user', actor_id=request.user.pk, actor_label=request.user.email,
           client_id=r.client_id, object=f'{r.name} {r.period:%b %Y}'[:254])
    stem, kind = {RULEBOOK: ('rulebook-snapshot', 'pdf'), METRICS: ('metrics', 'csv')}.get(r.name, ('audit-report', 'pdf'))
    response = FileResponse(r.file.open('rb'), as_attachment=True, filename=f'{stem}-{r.period:%Y-%m}.{kind}',
                            content_type='text/csv' if kind == 'csv' else 'application/pdf')
    response['Cache-Control'] = 'private, no-store'
    return response


class ReportsView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        return Response({'types': types(), 'runs': [row(r) for r in Report.objects.filter(client=request.user.client)[:100]]})

    def post(self, request):
        user, name = request.user, str(request.data.get('name') or '').strip()
        period = month_from(str(request.data.get('period') or ''))
        if name not in NAMES or period is None:
            return Response({'detail': 'Choose a report and a month.'}, status=status.HTTP_400_BAD_REQUEST)
        if not allowed_month(user.client, period):
            return Response({'detail': 'Choose a month from your start date to this month.'}, status=status.HTTP_400_BAD_REQUEST)
        if name == PERIOD:
            report = make_period(user.client, period, user.name, request)
        elif name == RULEBOOK:
            report = make_rulebook(user.client, period, user.name, request)
        elif name == METRICS:
            report = make_metrics(user.client, period, user.name, request)
        else:
            report = Report.objects.create(client=user.client, name=name[:120], period=period, status=Report.Status.UNAVAILABLE, made_by=user.name)
        return Response(row(report), status=status.HTTP_201_CREATED)


class PeriodReportView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        period = month_from(request.query_params.get('period') or '')
        if period is None:
            return Response({'detail': 'Give the month as YYYY-MM.'}, status=status.HTTP_400_BAD_REQUEST)
        if not allowed_month(request.user.client, period):
            return Response({'detail': 'Choose a month from your start date to this month.'}, status=status.HTTP_400_BAD_REQUEST)
        report = latest_or_make(request.user.client, period, request.user.name, request)
        if report.status != Report.Status.READY:
            return Response({'detail': 'This report was held back for a wording check; CiV has been told.'}, status=status.HTTP_409_CONFLICT)
        return send(request, report)


class ReportFileView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request, ref: str):
        pk = ref.removeprefix('rep-')
        r = Report.objects.filter(client=request.user.client, pk=(number(pk) or 0), status=Report.Status.READY,
                                  purged_at__isnull=True).exclude(file='').first()
        if r is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return send(request, r)
