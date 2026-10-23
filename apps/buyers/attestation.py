"""Module 15 step 2: the risk attestation (spec §9a, civ.attestation.v1) — monthly per company, with its SHA-256 and
older versions kept. Three blocks: frequency drivers (from the records and saved scores), records integrity (coverage,
completeness, fingerprints) and the company's signed statements with any conflict CiV measured. Every field carries its
value, source grade and whether it is a worst case; statements never raise a value. No contact-level row is included."""
import hashlib
import json
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .models import AttestationSnapshot, Statement

SCHEMA = 'civ.attestation.v1'
LOCK_DAYS = 5


def field(value, grade: str, worst: bool = False, note: str = '') -> dict:
    return {'value': value, 'grade': grade, 'worstCase': worst, **({'note': note} if note else {})}


def conflict(client, topic: str) -> tuple[str | None, str]:
    """(what CiV observed that conflicts, a short note) for a statement's topic."""
    from apps.consent.models import ConsentResult
    from apps.uploads.models import DncCheck, InternalListEntry
    since = timezone.now() - timedelta(days=90)
    results = ConsentResult.objects.filter(client=client, variant='strict', frozen=False, contact__occurred_at__gte=since)
    nothing = (None, 'Not measured yet: no checked contacts in the last 90 days')
    if topic == Statement.Topic.DNC:
        return (None, 'CiV reads your DNC check records') if DncCheck.objects.filter(client=client).exists() \
            else ('No DNC check records supplied, so CiV cannot see the checks', '')
    if topic == Statement.Topic.INTERNAL:
        if not InternalListEntry.objects.filter(client=client).exists():
            return 'Internal do-not-call list not supplied', ''
        from apps.scoring.extra import internal_list
        from apps.contacts.models import ContactEvent
        sent = ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, occurred_at__gte=since)
        if not sent.exists():
            return nothing
        n = internal_list(client, sent)['value']
        return (f'{n:,} contact{"" if n == 1 else "s"} after the number joined your internal list (90 days)', '') if n else (None, 'Matches what CiV measured')
    if topic in (Statement.Topic.OPTOUTS, Statement.Topic.CONSENT) and not results.exclude(status__in=['pending', 'not_needed']).exists():
        return nothing
    if topic == Statement.Topic.OPTOUTS:
        n = results.filter(codes__contains=['NP_AFTER_OPT_OUT']).count()
        return (f'{n:,} contact{"" if n == 1 else "s"} after an opt-out (90 days)', '') if n else (None, 'Matches what CiV measured')
    if topic == Statement.Topic.CONSENT:
        n = results.filter(is_legal_basis=True, status__in=['no_proof', 'conflicting']).count()
        return (f'{n:,} contact{"" if n == 1 else "s"} that need consent with none or conflicting proof (90 days)', '') if n \
            else (None, 'Matches what CiV measured')
    return None, 'Info only: CiV cannot check this'


def statements(client) -> dict:
    rows = list(Statement.objects.filter(client=client, withdrawn_at__isnull=True))
    out = {'statements': [], 'conflicts': [], 'statementRows': []}
    for s in rows:
        seen, note = conflict(client, s.topic)
        out['statementRows'].append({'id': f'st-{s.pk}', 'topic': s.topic, 'text': s.text, 'signedBy': s.signed_by,
                                     'signedOn': s.signed_at.date().isoformat(), 'conflict': seen, 'note': note})
        if seen:
            out['conflicts'].append({'stated': s.text, 'observed': seen, 'treatment': 'Measured value used; the statement is shown only',
                                     'ref': f'Statement signed by {s.signed_by}, {s.signed_at:%-d %b %Y}'})
        else:
            out['statements'].append(s.text)
    latest = rows[-1] if rows else None
    out['signedBy'] = latest.signed_by if latest else None
    out['asOf'] = latest.signed_at.date().isoformat() if latest else None
    return out


def reading(run) -> dict | None:
    """The month's Exposure reading in the shape the insurer pages use (pending factors are null)."""
    if run is None or not (run.score or {}).get('factors'):
        return None
    e = run.score.get('exposure', {})
    return {'factors': [f['value'] for f in run.score['factors']], 'venue': e.get('venue', {}).get('value', 1.0),
            'targeting': e.get('targeting', {}).get('value', 1.0), 'volume': e.get('volume', {}).get('value', 1.0),
            'source': f'Measured from records · {run.period:%b %Y}' + (' · partial' if run.score.get('partial') else '') + ' · draft bands'}


def build(client, period: date) -> dict:
    from apps.reconcile.api import attestation, rows
    from apps.reconcile.models import PeriodIntegrity
    from apps.vendors.models import VendorMonth
    from apps.scoring.models import SnapshotRun
    # the month's saved scores, or the newest month before it while this one is not scored yet
    run = SnapshotRun.objects.filter(client=client, period__lte=period).order_by('-period', '-version').first()
    score = (run.score if run else {}) or {}
    exposure = score.get('exposure') or {}
    coverage = score.get('coverage') or {}
    sheet = attestation(client)  # the records' last 30 days (Module 10 card coverage)
    drivers = {k: field(v, 'C') for k, v in sheet.items() if k not in ('monitoring', 'controls', 'selfReported')}
    by = {m.code: m for m in run.metrics.all()} if run else {}
    for code, key in (('M12', 'internalListContacts'), ('M11', 'reassignedCheckRate')):
        m = by.get(code)
        if m and m.state == 'worst_case':
            drivers[key] = field(None, 'N', True, m.data.get('note') or 'not supplied')
    vendors = VendorMonth.objects.filter(client=client, period=period, sub_id='').count()
    if vendors:
        drivers['vendors'] = field(vendors, 'C')
    from apps.docai.read import latest_answers
    files = latest_answers(client, 'policy_file')  # Module 16: only answers from an AI that passed its exam
    controls = {'policy': True if any(r.answers.get('kind') == 'tcpa_policy' for r in files) else None}
    contracts = latest_answers(client, 'contract_clauses')
    if contracts:  # contracts the AI read with the indemnity clause found
        signed = sum(bool(((r.answers.get('clauses') or {}).get('indemnity') or {}).get('found')) for r in contracts)
        drivers['vendorTermsShare'] = field(round(signed / len(contracts), 3), 'D')
    month = PeriodIntegrity.objects.filter(client=client, period=period).first()
    integrity = {'basisMix': [{'grade': g, 'share': round(100 * s, 1)} for g, s in (coverage.get('mix') or {}).items()],
                 'reconciliation': rows(month) if month else [],'evidenceCoverage': field(coverage.get('value'), 'A', False), 'coverageMix': coverage.get('mix') or {},
                 'completeness': field(month.completeness if month else None, 'B'), 'fingerprinted': field(sheet['controls']['fingerprinted'], 'A'),
                 'exposure': {'value': exposure.get('value'), 'grade': exposure.get('grade'), 'defect': score.get('defect'),
                              'partial': score.get('partial'), 'factors': score.get('factors') or []}}
    states = statements(client)
    return {'schema': SCHEMA, 'company': client.name, 'industry': client.industry, 'reading': reading(run), 'period': period.strftime('%Y-%m'), 'monitoring': sheet.get('monitoring'),
            'frequencyDrivers': drivers, 'recordsIntegrity': integrity, 'controls': controls,
            'insuredStates': {'statements': states['statements'], 'conflicts': states['conflicts'], 'signedBy': states['signedBy'], 'asOf': states['asOf']}}


def sha_of(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@transaction.atomic
def save(client, period: date, now=None) -> AttestationSnapshot | None:
    """The open month is replaced; a locked month gets a new version only when its content changed."""
    now = now or timezone.now()
    payload = build(client, period)
    sha = sha_of(payload)
    nxt = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    locked = now.date() >= nxt + timedelta(days=LOCK_DAYS)
    current = AttestationSnapshot.objects.filter(client=client, period=period).order_by('-version').first()
    if current and current.sha256 == sha:
        if locked and not current.locked:
            AttestationSnapshot.objects.filter(pk=current.pk).update(locked=True)
        return None
    if current and not current.locked:
        current.payload, current.sha256, current.locked = payload, sha, locked
        current.save()
        return current
    return AttestationSnapshot.objects.create(client=client, period=period, version=(current.version + 1) if current else 1,
                                              payload=payload, sha256=sha, locked=locked)
