"""Client API (Module 11 step 5): GET /api/reports — the report types and the report history; POST /api/reports {name, period} — "Generate": the period audit report, the Rulebook snapshot and the metric export
are made now; the evidence file and certification pack are made from the bulk export below the cards; the litigation
package is asked for as a quote (CiV staff see it under Quote requests and get an email, 2026-10-30); GET /api/reports/period?period=YYYY-MM — that month's report PDF (made if there is none yet);
GET /api/reports/rep-<id>/file — a past report. Every download is logged."""
import logging
from datetime import datetime

from django.http import FileResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.recorder import record
from apps.accounts.permissions import IsClientUser

from .make import METRICS, PERIOD, RULEBOOK, latest_or_make, make_metrics, make_period, make_rulebook
from .models import QuoteRequest, Report
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
ADD_ONS = {name for _, name, _, _, add_on in TYPES if add_on}
FROM_BULK = {'Evidence file export', 'Certification pack'}  # made from the bulk evidence export, not from a card


def open_quotes(client):
    """Requests still on their way (not closed by CiV, not released yet)."""
    return QuoteRequest.objects.filter(client=client, done_at__isnull=True).exclude(status=QuoteRequest.Status.RELEASED)


def types(client) -> list[dict]:
    """The cards; an add-on carries its open request (when asked, which step) and its last released package."""
    waiting = {q.name: q for q in open_quotes(client).order_by('asked_at')}
    released = {q.name: q for q in QuoteRequest.objects.filter(client=client, status=QuoteRequest.Status.RELEASED).order_by('released_at')}
    out = []
    for i, n, d, f, a in TYPES:
        q, r = waiting.get(n), released.get(n)
        out.append({'id': i, 'name': n, 'description': d, 'format': f, 'addOn': a, 'requestedAt': q.asked_at if q else None,
                    'quote': {'step': q.status, 'at': q.asked_at, 'madeAt': q.made_at, 'found': q.package_files, 'missing': q.package_missing} if q else None,
                    'released': {'at': r.released_at, 'url': f'/api/reports/quote-{r.pk}/file'} if r else None})
    return out


def allowed_month(client, period) -> bool:
    """From the client's first month to this one: no reports for months before CiV started or still to come."""
    from django.utils import timezone
    return client.start_date.replace(day=1) <= period <= timezone.localdate().replace(day=1)


def row(r: Report) -> dict:
    ready = r.status == Report.Status.READY and r.file and not r.purged_at
    return {'id': f'rep-{r.pk}', 'name': r.name, 'period': r.period.strftime('%b %Y') if r.period else '—', 'requestedBy': r.made_by,
            'at': r.made_at, 'status': 'ready' if ready else ('blocked' if r.status == Report.Status.BLOCKED else 'unavailable'),
            'url': f'/api/reports/rep-{r.pk}/file' if ready else None, 'sha256': r.sha256 or None}


QUOTE_STEPS = {'asked': 'requested', 'accepted': 'accepted', 'checking': 'checking', 'released': 'ready'}


def quote_row(q: QuoteRequest) -> dict:
    ready = q.status == QuoteRequest.Status.RELEASED and q.package
    return {'id': f'quote-{q.pk}', 'name': q.name, 'period': q.period.strftime('%b %Y') if q.period else '—', 'requestedBy': q.asked_by,
            'at': q.asked_at, 'status': 'closed' if q.done_at and not ready else QUOTE_STEPS[q.status],
            'url': f'/api/reports/quote-{q.pk}/file' if ready else None, 'sha256': q.package_sha256 if ready else None}


def ask_for_quote(request, name: str, period) -> QuoteRequest:
    """One open request per add-on: asking again returns it. New ones are logged and emailed to CiV staff."""
    user = request.user
    q = open_quotes(user.client).filter(name=name).first()
    if q is not None:
        return q
    q = QuoteRequest.objects.create(client=user.client, name=name, period=period, asked_by=user.name, asked_by_email=user.email)
    record('quote_requested', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
           client_id=user.client_id, object=name[:254])
    from .emails import quote_requested
    try:
        quote_requested(q)
    except Exception:  # a mail problem never loses the request; it is in the staff panel either way
        logging.getLogger(__name__).exception('Quote request email failed for %s', q.pk)
    return q


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
        client = request.user.client
        runs = [row(r) for r in Report.objects.filter(client=client).exclude(status=Report.Status.UNAVAILABLE)[:100]]
        runs += [quote_row(q) for q in QuoteRequest.objects.filter(client=client)[:100]]
        return Response({'types': types(client), 'runs': sorted(runs, key=lambda r: r['at'], reverse=True)[:100]})

    def post(self, request):
        user, name = request.user, str(request.data.get('name') or '').strip()
        period = month_from(str(request.data.get('period') or ''))
        if name not in NAMES or period is None:
            return Response({'detail': 'Choose a report and a month.'}, status=status.HTTP_400_BAD_REQUEST)
        if name in FROM_BULK:
            return Response({'detail': 'Paste the numbers in the bulk evidence export below the cards.'}, status=status.HTTP_400_BAD_REQUEST)
        if name in ADD_ONS:
            q = ask_for_quote(request, name, period)
            return Response(quote_row(q), status=status.HTTP_201_CREATED)
        if not allowed_month(user.client, period):
            return Response({'detail': 'Choose a month from your start date to this month.'}, status=status.HTTP_400_BAD_REQUEST)
        if name == PERIOD:
            report = make_period(user.client, period, user.name, request)
        elif name == RULEBOOK:
            report = make_rulebook(user.client, period, user.name, request)
        else:  # the metric export
            report = make_metrics(user.client, period, user.name, request)
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


class LitigationView(APIView):
    """POST /api/reports/litigation {numbers: [...]}: after CiV accepted the quote, the client's Admin or lawyer sends up
    to 25 numbers; CiV makes the package (numbers turned into phone codes in memory, never stored) and staff check it."""
    permission_classes = [IsClientUser]

    def post(self, request):
        import json
        from apps.evidence.bundle import MAX_NUMBERS
        from .litigation import make
        from .words import banned_words
        user = request.user
        if not (user.is_admin or user.is_counsel):
            return Response({'detail': 'Only an Admin or your lawyer can send the numbers.'}, status=status.HTTP_403_FORBIDDEN)
        q = open_quotes(user.client).filter(status__in=[QuoteRequest.Status.ACCEPTED, QuoteRequest.Status.CHECKING]).first()
        if q is None:
            return Response({'detail': 'CiV has not accepted a litigation package request yet.'}, status=status.HTTP_409_CONFLICT)
        numbers = request.data.get('numbers')
        typed = [str(n)[:40] for n in numbers if isinstance(n, (str, int)) and str(n).strip()] if isinstance(numbers, list) else []
        if not typed:
            return Response({'detail': 'Type at least one phone number.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(typed) > MAX_NUMBERS:
            return Response({'detail': f'Up to {MAX_NUMBERS} numbers.'}, status=status.HTTP_400_BAD_REQUEST)
        from apps.evidence.bundle import files_for, resolve
        bad = banned_words(json.dumps(files_for(user.client, resolve(user.client, typed)[0]), default=str, ensure_ascii=False))
        if bad:
            record('evidence_file_blocked', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
                   client_id=user.client_id, object=f'litigation · {", ".join(bad)}'[:254])
            return Response({'detail': 'These files were held back for a wording check; CiV has been told.'}, status=status.HTTP_409_CONFLICT)
        files, missing = make(q, typed, user.name)
        record('litigation_package_made', request=request, actor_kind='client_user', actor_id=user.pk, actor_label=user.email,
               client_id=user.client_id, object=f'{len(files)} found · {len(missing)} not found · sha256 {q.package_sha256}'[:254])
        from .emails import package_made
        try:
            package_made(q)
        except Exception:
            logging.getLogger(__name__).exception('Package email failed for %s', q.pk)
        return Response({'found': len(files), 'missing': len(missing), 'row': quote_row(q)}, status=status.HTTP_201_CREATED)


def send_package(request, q: QuoteRequest, actor_kind: str):
    record('litigation_package_downloaded', request=request, actor_kind=actor_kind, actor_id=request.user.pk, actor_label=request.user.email,
           client_id=q.client_id, object=f'{q} · sha256 {q.package_sha256}'[:254])
    response = FileResponse(q.package.open('rb'), as_attachment=True, filename=f'litigation-package-{q.asked_at:%Y%m%d}.zip',
                            content_type='application/zip')
    response['Cache-Control'] = 'private, no-store'
    return response


class ReportFileView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request, ref: str):
        if ref.startswith('quote-'):
            q = QuoteRequest.objects.filter(client=request.user.client, pk=(number(ref.removeprefix('quote-')) or 0),
                                            status=QuoteRequest.Status.RELEASED).exclude(package='').first()
            if q is None:
                return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
            return send_package(request, q, 'client_user')
        pk = ref.removeprefix('rep-')
        r = Report.objects.filter(client=request.user.client, pk=(number(pk) or 0), status=Report.Status.READY,
                                  purged_at__isnull=True).exclude(file='').first()
        if r is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return send(request, r)
