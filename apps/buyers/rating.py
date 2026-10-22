"""Module 15: the insurer's rating engine settings and the "Send to rating engine" button. Buyers only; the key is
locked when saved and never sent back. The monthly send runs on the 6th, after the month's sheet is locked."""
import re
from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.connections.crypto import lock

from .authentication import IsBuyerUser
from .engines import check_address, send
from .models import AttestationSnapshot, BuyerLink, RatingEngine, RatingSend
from .portal import as_buyer, newest


def view(org) -> dict:
    engine = RatingEngine.objects.filter(org=org).first()
    # Older sends may have saved the other server's web page: shown without its code (2026-10-23).
    clean = lambda text: re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', text)).strip()  # noqa: E731
    sends = [{'at': s.sent_at, 'company': s.company, 'ok': s.ok, 'detail': clean(s.detail), 'by': s.by} for s in RatingSend.objects.filter(org=org)[:10]]
    if engine is None:
        return {'url': '', 'keyHint': '', 'monthly': False, 'sends': sends}
    return {'url': engine.url, 'keyHint': engine.key_hint, 'monthly': engine.monthly, 'adapter': engine.get_adapter_display(), 'sends': sends}


class RatingEngineView(APIView):
    permission_classes = [IsBuyerUser]

    def get(self, request):
        return as_buyer(Response(view(request.user.org)))

    def post(self, request):
        org = request.user.org
        url = str(request.data.get('url', '')).strip()
        key = str(request.data.get('key', '')).strip()
        problem = check_address(url) if url else 'Enter the address of your rating engine.'
        if problem:
            return as_buyer(Response({'detail': problem}, status=400))
        engine = RatingEngine.objects.filter(org=org).first() or RatingEngine(org=org)
        if not key and not engine.key:
            return as_buyer(Response({'detail': 'Enter the key your rating engine gave you.'}, status=400))
        engine.url, engine.monthly, engine.updated_by = url, bool(request.data.get('monthly')), request.user.name
        if key:
            engine.key, engine.key_hint = lock({'key': key}), key[-4:]
        engine.save()
        return as_buyer(Response(view(org)))

    def delete(self, request):
        RatingEngine.objects.filter(org=request.user.org).delete()
        return as_buyer(Response(view(request.user.org)))


class SendView(APIView):
    permission_classes = [IsBuyerUser]

    def post(self, request):
        engine = RatingEngine.objects.filter(org=request.user.org).select_related('org').first()
        if engine is None:
            return as_buyer(Response({'detail': 'Add your rating engine address and key first.'}, status=400))
        pk = str(request.data.get('insured', '')).removeprefix('c-')
        snap = newest().filter(client_id=pk).first() if pk.isdigit() else None  # only a company sharing right now
        if snap is None:
            return as_buyer(Response({'detail': 'This company does not share with you.'}, status=404))
        row = send(engine, snap, request.user.name)
        # The plain message on screen; the history keeps the short technical answer too (2026-10-23).
        return as_buyer(Response({'ok': row.ok, 'detail': row.detail.split(' Technical answer:')[0]}, status=200 if row.ok else 502))


def send_monthly(today=None) -> int:
    """For each insurer that asked for it: every sharing company's locked sheet of last month, once."""
    today = today or timezone.localdate()
    period = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    sent = 0
    for engine in RatingEngine.objects.filter(monthly=True, org__is_active=True).select_related('org'):
        for link in BuyerLink.objects.filter(org=engine.org):
            if not link.active(today):
                continue
            snap = AttestationSnapshot.objects.filter(client_id=link.client_id, period=period, locked=True).order_by('-version').first()
            if snap and not RatingSend.objects.filter(org=engine.org, snapshot=snap, ok=True).exists():
                send(engine, snap, 'Monthly send')
                sent += 1
    return sent
