"""Module 15 step 3: the insurer pages for a signed-in buyer, from each shared company's newest attestation snapshot,
or (owner, 2026-10-30, option B) the snapshot of a month the insurer picks: only months from when that company started
sharing with this insurer. Fields CiV does not measure yet are null or empty, never sample values.
The buyer scope already hides companies that do not share right now; each opened sheet goes into that company's log."""
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.models import AccessEntry
from apps.access_log.recorder import record

from apps.accounts.permissions import IsClientUser

from .authentication import IsBuyerUser
from apps.refs import number

from .models import AttestationSnapshot, BuyerUser

NOT_MEASURED = ('marketingShare', 'smsShare', 'optOutMedianHours', 'optOutFailShare', 'rndExposure',
                'litigatorContacts', 'unknownCallerIds')
MEASURED = ('vendorTermsShare', 'consentProof', 'prerecordedShare', 'purchasedShare', 'contactsAfterOptOut', 'reAdded', 'internalListContacts',
            'reassignedCheckRate', 'manualImportShare', 'evidenceFoundShare')


def newest():
    return AttestationSnapshot.objects.order_by('client_id', '-period', '-version').distinct('client_id')


def shared_since(user) -> dict[int, object]:
    """{company id: first month this insurer may see} for every company sharing with this user's insurer now."""
    from .models import BuyerLink
    today, out = timezone.localdate(), {}
    for link in BuyerLink.objects.filter(org=user.org).select_related('client', 'org'):
        if link.active(today):
            first = link.granted_at.date().replace(day=1)
            out[link.client_id] = min(first, out.get(link.client_id, first))
    return out


def chosen(request):
    """The month picked in the top bar, as its first day, or None (the newest)."""
    from apps.refs import month_span
    span = month_span(request.query_params.get('period'))
    return span[0] if span else None


def sheet_of(client_id: int, month):
    return AttestationSnapshot.objects.filter(client_id=client_id, period=month).order_by('-version').first()


def buyer_periods(user) -> list[dict]:
    """The insurer's month picker: months with a sheet of a sharing company, from when that company started sharing."""
    months = set()
    for client_id, first in shared_since(user).items():
        months |= set(AttestationSnapshot.objects.filter(client_id=client_id, period__gte=first).values_list('period', flat=True))
    return [{'id': m.strftime('%Y-%m'), 'label': m.strftime('%b %Y')} for m in sorted(months, reverse=True)]


def insured(snap: AttestationSnapshot) -> dict:
    """One snapshot in the portal's Insured shape."""
    p = snap.payload
    drivers, integrity, states = p.get('frequencyDrivers', {}), p.get('recordsIntegrity', {}), p.get('insuredStates', {})
    value = lambda block, key: (block.get(key) or {}).get('value')  # noqa: E731
    out = {k: None for k in NOT_MEASURED} | {k: value(drivers, k) for k in MEASURED}
    out.update({
        'id': f'c-{snap.client_id}', 'name': p.get('company', ''), 'industry': p.get('industry') or '',
        'contactsPerMonth': value(drivers, 'contactsPerMonth'), 'selfReported': False,
        'asOf': snap.made_at.date().isoformat(), 'sheetHash': snap.sha256[:12], 'monitoring': p.get('monitoring') or 'Not yet',
        'signedBy': states.get('signedBy'), 'vendors': value(drivers, 'vendors'),
        'praStates': None, 'priorStated': None, 'priorDocket': None, 'openMatters': None,
        'coverage': value(integrity, 'evidenceCoverage'), 'completeness': value(integrity, 'completeness'),
        'basisMix': integrity.get('basisMix', []), 'reconciliation': integrity.get('reconciliation', []),
        'conflicts': states.get('conflicts', []), 'statements': states.get('statements', []),
        'controls': {'policy': (p.get('controls') or {}).get('policy'), 'trainingCurrency': None, 'optOutTests90d': None, 'fingerprinted': value(integrity, 'fingerprinted') or 0},
        'exposure': {'inside': p.get('reading'), 'outside': None, 'why': {'venue': '', 'targeting': '', 'volume': ''}},
    })
    return out


def seen(request, client_id: int) -> None:
    """Once a day per person and company: the company sees in its access log that its insurer opened the sheet."""
    user = request.user
    label = f'{user.name} ({user.org.name})'
    today = timezone.localdate()
    if not AccessEntry.objects.filter(action='attestation_viewed', actor_kind='buyer', actor_id=user.pk, client_id=client_id, at__date=today).exists():
        record('attestation_viewed', request=request, actor_kind='buyer', actor_id=user.pk, actor_label=label, client_id=client_id,
               object='Risk Attestation')


def as_buyer(response: Response) -> Response:
    response['X-CiV-Viewer'] = 'buyer'  # the portal shows this as it is, with no sample filled in
    return response


def own_sheet(client, month=None) -> AttestationSnapshot | None:
    """A client's own sheet, as its insurer sees it (owner decision 2026-10-22): the newest, made now if none yet; or
    that month's (the month picker, 2026-10-30), None when that month has none."""
    if month is not None and month != timezone.localdate().replace(day=1):
        return sheet_of(client.pk, month)
    if month is not None and (snap := sheet_of(client.pk, month)):
        return snap
    snap = AttestationSnapshot.objects.filter(client=client).order_by('-period', '-version').first()
    if snap is None:
        from .attestation import save
        snap = save(client, timezone.localdate().replace(day=1)) or AttestationSnapshot.objects.filter(client=client).first()
    return snap


def previewing(user) -> bool:
    from apps.accounts.models import ClientUser
    return isinstance(user, ClientUser) and user.view == 'underwriter'


class InsuredsView(APIView):
    """An insurer's portfolio; a client user in the Underwriter view gets only its own company, as its insurer sees it."""
    permission_classes = [IsBuyerUser | IsClientUser]

    def get(self, request):
        month = chosen(request)
        if previewing(request.user):
            sheet = own_sheet(request.user.client, month)
            return as_buyer(Response([insured(sheet)] if sheet else []))
        if not isinstance(request.user, BuyerUser):
            return Response({'detail': 'Switch to the Underwriter view to see this.'}, status=403)
        if month is None:
            sheets = list(newest())
        else:  # that month's sheet of each company that shared with this insurer by then
            sheets = [s for cid, first in shared_since(request.user).items() if month >= first and (s := sheet_of(cid, month))]
        rows = sorted((insured(s) for s in sheets), key=lambda i: i['name'].lower())
        return as_buyer(Response(rows))


def one(request, ref: str) -> Response:
    pk, month = number(ref.removeprefix('c-')), chosen(request)
    snap = newest().filter(client_id=pk).first() if pk else None
    if snap is None:
        return as_buyer(Response({'detail': 'This company does not share with you.'}, status=404))
    if month is not None:
        first = shared_since(request.user).get(pk)
        snap = sheet_of(pk, month) if first and month >= first else None
        if snap is None:
            return as_buyer(Response({'detail': f'No sheet for {month:%b %Y}.'}, status=404))
    seen(request, snap.client_id)
    return as_buyer(Response(insured(snap)))
