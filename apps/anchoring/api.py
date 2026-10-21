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
        from django.utils import timezone
        client = request.user.client
        held = Fingerprint.objects.filter(client=client).count()
        anchors = MerkleAnchor.objects.filter(client=client)
        last = anchors.order_by('-day').first()
        with_records = {d.replace(day=1) for d in Fingerprint.objects.filter(client=client).dates('fetched_at', 'month')}
        today = timezone.localdate()
        span = months(min([client.start_date, *with_records]) if with_records else client.start_date, today)
        this_month, first = today.replace(day=1), client.start_date.replace(day=1)

        def state(m):
            if m < first:
                return 'before'  # before CiV started
            return 'covered' if m in with_records and m < this_month else 'partial'  # this month, or a month with no records
        coverage = [{'label': m.strftime('%b %Y'), 'state': state(m)} for m in span[-12:]]
        return Response({'artifacts': f'{held:,}', 'anchors': anchors.count(), 'lastAnchor': last.day.isoformat() if last else '—',
                         'engagedSince': client.start_date.isoformat(), 'coverage': coverage})


class PositionView(APIView):
    """GET ?phone=&date=: what CiV held about a number on a day. The number is never stored."""
    permission_classes = [IsClientUser]

    def get(self, request):
        from .position import position
        try:
            day = date.fromisoformat(request.query_params.get('date', ''))
        except ValueError:
            return Response({'detail': 'Enter a date.'}, status=400)
        found = position(request.user.client, request.query_params.get('phone', ''), day)
        return Response(found) if found else Response({'detail': 'Enter a full phone number.'}, status=400)


class HashCheckView(APIView):
    permission_classes = [IsClientUser]

    def get(self, request):
        from .position import hash_check
        return Response(hash_check(request.user.client, request.query_params.get('hash', '')))
