"""Client API: the Evidence Vault's numbers that are real now — records held (fingerprints), daily seals, the last
seal, and which months have records. Fields not known yet are left out (the portal keeps its sample for them)."""
from datetime import date, timedelta

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsClientUser
from apps.ledger.models import Fingerprint

from .models import MerkleAnchor


def months(start: date, end: date) -> list[date]:
    out, day = [], start.replace(day=1)
    while day <= end:
        out.append(day)
        day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


class VaultView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        """[?period=YYYY-MM] (the month picker, owner 2026-10-30): records read and days sealed in that month, and the
        coverage strip ending with it. Without a month: everything up to today."""
        from django.utils import timezone

        from apps.refs import month_span
        client = request.user.client
        prints, anchors = Fingerprint.objects.filter(client=client), MerkleAnchor.objects.filter(client=client)
        chosen = month_span(request.query_params.get('period'))
        if chosen:
            prints = prints.filter(fetched_at__date__gte=chosen[0], fetched_at__date__lt=chosen[1])
            anchors = anchors.filter(day__gte=chosen[0], day__lt=chosen[1])
        held = prints.count()
        last = anchors.order_by('-day').first()
        with_records = {d.replace(day=1) for d in Fingerprint.objects.filter(client=client).dates('fetched_at', 'month')}
        today = timezone.localdate()
        end = min(today, chosen[1] - timedelta(days=1)) if chosen else today
        span = months(min([client.start_date, *with_records]) if with_records else client.start_date, end)
        this_month, first = today.replace(day=1), client.start_date.replace(day=1)

        def state(m):
            if m < first:
                return 'before'  # before CiV started
            return 'covered' if m in with_records and m < this_month else 'partial'  # this month, or a month with no records
        coverage = [{'label': m.strftime('%b %Y'), 'state': state(m)} for m in span[-12:]]
        return Response({'artifacts': f'{held:,}', 'anchors': anchors.count(), 'lastAnchor': last.day.isoformat() if last else None,
                         'engagedSince': client.start_date.isoformat(), 'coverage': coverage,
                         'period': chosen[0].strftime('%b %Y') if chosen else None,
                         'deletedUnderRetention': deleted_under_retention(client)})


def deleted_under_retention(client) -> int:
    """Files deleted after their 4 years (not under a hold); their fingerprints are kept (real count, 2026-10-23)."""
    from apps.captures.models import PageCapture
    from apps.provenance.models import ProofRequest
    from apps.reports.models import Report
    from apps.uploads.models import UploadedFile
    from apps.vendors.models import VendorContract
    return sum(m.objects.filter(client=client, purged_at__isnull=False).count()
               for m in (UploadedFile, PageCapture, VendorContract, Report, ProofRequest))


class PositionView(APIView):
    """GET ?phone=&date=: what CiV held about a number on a day. The number is never stored."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from .position import position
        from django.utils import timezone

        from apps.refs import day as read_day
        day = read_day(request.query_params.get('date'))
        if day is None:
            return Response({'detail': 'Enter a date.'}, status=400)
        if day > timezone.localdate():
            return Response({'detail': 'Choose a date up to today.'}, status=400)
        found = position(request.user.client, request.query_params.get('phone', ''), day)
        return Response(found) if found else Response({'detail': 'Enter a full phone number.'}, status=400)


class HashCheckView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        from .position import hash_check
        return Response(hash_check(request.user.client, request.query_params.get('hash', '')))
