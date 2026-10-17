"""The consent part of a number's page: the current owner's proofs, what the latest contact needed and whether each
need passed, the history of changes, and the checks CiV cannot run yet. Strict results only."""
from apps.optouts.models import OptOutEvent
from apps.rulebook.lookup import current_version

from .models import ConsentProof, ConsentResult, ResultChange
from .words import CHANGE_REASONS, NOT_MEASURED, portal_status

WORST_FIRST = ['NO_PROOF', 'CONFLICTING', 'WEAK', 'VERIFIED']
KIND = {'certificate': 'Consent certificate', 'self_asserted': 'CRM consent field (never enough alone)',
        'ebr_purchase': 'Existing customer: purchase', 'ebr_inquiry': 'Existing customer: inquiry'}


def worst_of(results) -> str:
    """A number's standing: its worst counted contact. Pending, frozen and "not needed" are left out; nothing checked
    yet is "not checked", never a worst case."""
    counted = [portal_status(r) for r in results if r is not None and not r.frozen and r.status not in ('pending', 'not_needed')]
    for status in WORST_FIRST:
        if status in counted:
            return status
    if any(r is not None and r.status == 'pending' for r in results):
        return 'PENDING'
    if any(r is not None for r in results):
        return 'NOT_NEEDED'
    return 'NOT_CHECKED'


def optouts_of(client, token: str) -> list[dict]:
    return [{'at': o.at, 'channel': o.channel, 'method': o.get_method_display()}
            for o in OptOutEvent.objects.filter(client=client, phone_token=token).order_by('at')]


def _proof(p: ConsentProof, used: int) -> dict:
    claim = p.certificate
    return {'id': f'cp-{p.pk}', 'kind': KIND.get(p.kind, p.kind), 'provider': claim.get_provider_display() if claim else None,
            'madeAt': p.when(), 'dateKnown': p.date_known, 'expiresAt': claim.cert_expires_at if claim else None,
            'state': claim.get_state_display() if claim else None, 'tool': p.source_system, 'withdrawn': p.withdrawn_at is not None,
            'usedBy': used}


def consent_panel(client, token: str, epoch, results) -> dict:
    results = [r for r in results if r is not None]
    proofs = ConsentProof.objects.filter(client=client, phone_token=token, epoch=epoch).select_related('certificate') if epoch else []
    used: dict[int, int] = {}
    for r in results:  # each contact once, however many of its needs the proof covered
        for proof_id in {b['proof'] for b in r.bases if b.get('proof')}:
            used[proof_id] = used.get(proof_id, 0) + 1
    latest = max((r for r in results if r.status != 'not_needed'), key=lambda r: r.contact.occurred_at, default=None)
    names = {p.pk: KIND.get(p.kind, p.kind) for p in proofs}
    changes = (ResultChange.objects.filter(client=client, contact__phone_token=token, variant='strict')
               .select_related('contact').order_by('-at', '-pk')[:20])
    try:
        draft = current_version().status != 'approved'
    except LookupError:
        draft = True
    return {
        'owner': epoch.number if epoch else None,
        'proofs': [_proof(p, used.get(p.pk, 0)) for p in proofs],
        'needs': [{'basis': b['basis'], 'status': b['status'].upper(), 'proof': names.get(b.get('proof'))} for b in (latest.bases if latest else [])],
        'needsFor': latest.contact.occurred_at if latest else None,
        'history': [{'at': c.at, 'contactAt': c.contact.occurred_at, 'from': c.old_status.upper() or None, 'to': c.new_status.upper(),
                     'reason': CHANGE_REASONS.get(c.reason, c.reason), 'frozen': c.reason == 'frozen'} for c in changes],
        'frozen': sum(1 for r in results if r.frozen),
        'pending': sum(1 for r in results if r.status == ConsentResult.Status.PENDING and not r.frozen),
        'notMeasured': list(NOT_MEASURED.values()),
        'draftRules': draft,
    }
