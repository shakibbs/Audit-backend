"""The number page's eight proof elements (what a defence needs for this number), from what CiV holds for the current
owner: present or not, who captured it (evidence tier), when, and its fingerprint."""
from apps.captures.models import PageCapture
from apps.consent.models import ConsentProof
from apps.consent.sources import CUSTODY, custody_of
from apps.ledger.models import Fingerprint
from apps.optouts.models import OptOutEvent
from apps.provenance.models import Provenance
from apps.uploads.models import InternalListEntry, RndQuery

GRADE_TIER = {'A': 1, 'B': 2, 'C': 3, 'D': 4}


def element(number, name, present, tier=None, sha=None, source=None, at=None, applies=True, holder=None):
    return {'number': number, 'element': name, 'applies': applies, 'present': present, 'tier': tier, 'hash': sha,
            'source': source, 'capturedAt': at, 'holder': holder}


def latest_print(client, system: str, record: str):
    return Fingerprint.objects.filter(client=client, source_system=system, source_record_id=record).order_by('-fetched_at').first()


def proof_elements(client, token: str, epoch, contacts: list, results: dict) -> list[dict]:
    counted = [results.get(c.pk) for c in contacts if c.is_primary]
    checked = [r for r in counted if r is not None and r.status not in ('pending', 'not_needed') and not r.frozen]
    out = [element(1, 'Every contact VERIFIED or WEAK', all(r.status in ('verified', 'weak') for r in checked) if checked else None)]

    proofs = ConsentProof.objects.filter(client=client, phone_token=token, epoch=epoch, withdrawn_at__isnull=True).select_related('certificate')
    cert = next((p for p in proofs if p.certificate_id), None)
    page = None
    if cert and cert.certificate.page:
        page = PageCapture.objects.filter(client=client, page__address=cert.certificate.page, ok=True).order_by('-captured_at').first()
    out.append(element(2, 'Consent page as of that date', bool(page) if cert else None, 1 if page else None,
                       page.fingerprint_sha256 if page else None, 'CiV page capture' if page else None, page.captured_at if page else None,
                       holder='CiV (page photo, kept privately)' if page else None))
    cert_print = latest_print(client, cert.certificate.provider, cert.certificate.cert_ref) if cert else None
    out.append(element(3, 'Third-party proof', bool(cert and cert.certificate.state == 'claimed'), 2 if cert_print else None,
                       cert_print.sha256 if cert_print else None, cert.certificate.get_provider_display() if cert else None,
                       cert.certificate.claimed_at if cert else None,
                       holder=CUSTODY[custody_of(cert.certificate)] if cert else None))  # who holds the original (2026-10-23)

    trace = Provenance.objects.filter(client=client, phone_token=token, epoch=epoch).first()
    lead = latest_print(client, trace.lead_system, trace.lead_record_id) if trace and trace.lead_record_id else None
    traced = trace is not None and trace.basis != 'untraced'
    out.append(element(4, 'Lead source', traced if trace else None, GRADE_TIER.get(lead.source_grade) if lead else None,
                       lead.sha256 if lead else None, (trace.source_name or trace.get_basis_display()) if traced else None,
                       trace.lead_received_at if trace else None))

    last = max((c for c in contacts if c.is_primary), key=lambda c: c.occurred_at, default=None)
    log = latest_print(client, last.source_system, last.source_record_id) if last else None
    out.append(element(5, 'Contact log with required fields', bool(log), GRADE_TIER.get(log.source_grade) if log else None,
                       log.sha256 if log else None, last.source_system if last else None, log.fetched_at if log else None))

    stop = OptOutEvent.objects.filter(client=client, phone_token=token).order_by('-at').first()
    stop_print = latest_print(client, stop.source_system, stop.source_record_id) if stop else None
    texting = client.connections.filter(kind='sms').exists()
    out.append(element(6, 'Opt-out history synced', bool(stop_print) or texting, GRADE_TIER.get(stop_print.source_grade) if stop_print else 3 if texting else None,
                       stop_print.sha256 if stop_print else None, stop.source_system if stop else ('Texting tool' if texting else None),
                       stop.at if stop else None))

    entry = InternalListEntry.objects.filter(client=client).select_related('upload').order_by('-upload__received_at').first()
    out.append(element(7, 'Internal list checked', True if entry else None, 4 if entry else None, entry.upload.sha256 if entry else None,
                       'Upload' if entry else None, entry.upload.received_at if entry else None))

    query = RndQuery.objects.filter(client=client, phone_token=token).select_related('upload').order_by('-queried_on').first()
    out.append(element(8, 'Your pre-contact reassigned check', (query.result == 'no') if query else None, 4 if query else None,
                       query.upload.sha256 if query else None, 'Upload' if query else None, query.upload.received_at if query else None))
    return out
