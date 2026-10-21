"""Module 14 step 1: the evidence file for one number (spec §9 "Evidence file", decision D18 open for what ships to
court). Built only from CiV's own data: everything the number page shows, plus, for every record behind it, the
fingerprint of what CiV saw, the tool and record it came from, when CiV fetched it, the day's seal (Merkle root, the
record's path to it, the timestamps) and whether the fingerprint still matches its seal. The number appears masked only
(CiV never stores it, owner decision 2026-10-22); the client's lawyer adds the real number from the client's records."""
from apps.anchoring.seal import verify
from apps.consent.models import ConsentProof
from apps.contacts.api import contacts_of, number_file
from apps.ledger.models import Fingerprint
from apps.optouts.models import OptOutEvent

DISCLAIMER = ('Comply iV measures and records. It operates no controls, sits in no call path and makes no compliance decisions. '
              'Findings are measurements, not legal advice. Comply iV is not a law firm.')
SEAL_WORDS = {'matches': 'Matches its seal', 'changed': 'Does not match its seal', 'not_sealed': 'Not sealed yet (sealed tonight)'}


def records_of(client, token: str, contacts) -> list[tuple[str, str, str]]:
    """(what, tool, record ID) of every record behind the file: contacts, consent proofs, certificates, opt-outs."""
    out = [(f'{c.get_channel_display()} {c.occurred_at:%d %b %Y %H:%M} UTC', c.source_system, c.source_record_id) for c in contacts]
    for p in ConsentProof.objects.filter(client=client, phone_token=token).select_related('certificate'):
        out.append((f'Consent proof: {p.get_kind_display()}', p.source_system, p.source_record_id))
        if p.certificate_id:
            out.append(('Certificate', p.certificate.provider, p.certificate.cert_ref))
    for o in OptOutEvent.objects.filter(client=client, phone_token=token):
        out.append((f'Opt-out {o.at:%d %b %Y}', o.source_system, o.source_record_id))
    return list(dict.fromkeys(out))


def fingerprints(client, records) -> list[dict]:
    out = []
    for what, tool, record in records:
        for fp in Fingerprint.objects.filter(client=client, source_system=tool, source_record_id=record).select_related('anchor').order_by('fetched_at'):
            a = fp.anchor
            out.append({'what': what, 'tool': tool, 'record': record, 'grade': fp.source_grade, 'sha256': fp.sha256, 'fetchedAt': fp.fetched_at,
                        'seal': {'day': a.day.isoformat(), 'root': a.root, 'leaf': fp.leaf_index, 'path': fp.merkle_path,
                                 'timestamp': a.tsa_time.isoformat() if a.tsa_time else None, 'bitcoin': bool(a.ots_proof)} if a else None,
                        'check': SEAL_WORDS[verify(fp)], 'atSource': at_source(client, tool, record)})
    return out


def at_source(client, tool: str, record: str) -> dict | None:
    """The latest re-fetch check of this record (step 2), or None when it was never asked again."""
    from .refetch import latest
    found = latest(client, tool, record)
    return {'result': found.get_result_display(), 'checkedAt': found.checked_at} if found else None


def build(client, ref: str) -> dict | None:
    page = number_file(client, ref)
    if page is None:
        return None
    contacts = contacts_of(client, ref)
    token = contacts[-1].phone_token
    prints = fingerprints(client, records_of(client, token, contacts))
    return {'company': client.name, 'number': page['phone'], 'ref': ref, 'note': 'The full number is not held by CiV; add it from your own records.',
            'owners': page['epochs'], 'contacts': page['contacts'], 'proofElements': page['proofElements'], 'optOuts': page['optOuts'],
            'listChecks': page['listChecks'], 'cameFrom': page['cameFrom'], 'consent': page['consent'], 'seal': page['anchor'],
            'fingerprints': prints, 'disclaimer': DISCLAIMER}
