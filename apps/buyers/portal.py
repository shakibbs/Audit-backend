"""Module 15 step 3: the insurer pages for a signed-in buyer, from each shared company's newest attestation snapshot
only (owner decision 2026-10-22: newest only). Fields CiV does not measure yet are null or empty, never sample values.
The buyer scope already hides companies that do not share right now; each opened sheet goes into that company's log."""
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_log.models import AccessEntry
from apps.access_log.recorder import record

from apps.accounts.permissions import IsClientUser

from .authentication import IsBuyerUser
from .models import AttestationSnapshot, BuyerUser

NOT_MEASURED = ('marketingShare', 'smsShare', 'optOutMedianHours', 'optOutFailShare', 'rndExposure',
                'litigatorContacts', 'unknownCallerIds')
MEASURED = ('vendorTermsShare', 'consentProof', 'prerecordedShare', 'purchasedShare', 'contactsAfterOptOut', 'reAdded', 'internalListContacts',
            'reassignedCheckRate', 'manualImportShare', 'evidenceFoundShare')


def newest():
    return AttestationSnapshot.objects.order_by('client_id', '-period', '-version').distinct('client_id')


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


def own_sheet(client) -> AttestationSnapshot:
    """A client previewing its insurer's view (owner decision 2026-10-22): its own newest sheet, made now if none yet."""
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
        if previewing(request.user):
            return as_buyer(Response([insured(own_sheet(request.user.client))]))
        if not isinstance(request.user, BuyerUser):
            return Response({'detail': 'Switch to the Underwriter view to see this.'}, status=403)
        rows = sorted((insured(s) for s in newest()), key=lambda i: i['name'].lower())
        return as_buyer(Response(rows))


def one(request, ref: str) -> Response:
    pk = ref.removeprefix('c-')
    snap = newest().filter(client_id=pk).first() if pk.isdigit() else None
    if snap is None:
        return as_buyer(Response({'detail': 'This company does not share with you.'}, status=404))
    seen(request, snap.client_id)
    return as_buyer(Response(insured(snap)))
