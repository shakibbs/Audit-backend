"""Module 12: the consent link in a vendor lead file (owner decision 2026-10-22: vendors send each lead with its
TrustedForm certificate URL or Jornaya LeadiD). Each link is queued to be claimed in the client's own account, like a
link found in a CRM record; the row's phone is matched to the certificate while the number is in memory (never kept),
and the certificate becomes the number's consent proof, labelled as from a vendor."""
from datetime import timedelta

from django.db import IntegrityError, transaction

from apps.certificates.claim import match_now
from apps.certificates.models import CertificateClaim
from apps.certificates.scan import found_in, window_hours
from apps.consent.models import ConsentProof
from apps.consent.proofs import _save

SOURCE = 'vendor_lead_file'
CERT = ('certificate', 'certificateurl', 'trustedform', 'trustedformurl', 'trustedformcerturl', 'xxtrustedformcerturl', 'certurl',
        'jornaya', 'leadidtoken', 'jornayaleadid', 'universalleadid', 'consentlink', 'consenturl')


def claims_for(client, text: str, received_at) -> list[CertificateClaim]:
    found = found_in(text.encode())
    if not found and text.strip():  # a bare Jornaya token in its own column
        found = found_in(f'leadid_token={text.strip()}'.encode())
    deadline = received_at + timedelta(hours=window_hours())
    out = []
    for provider, ref in found:
        try:
            with transaction.atomic():
                out.append(CertificateClaim.objects.create(client=client, provider=provider, cert_ref=ref, deadline_at=deadline))
        except IntegrityError:
            out.append(CertificateClaim.objects.get(client=client, provider=provider, cert_ref=ref))  # already queued
    return out


def link_certificates(upload, rows: list[tuple]) -> int:
    """rows: (number, phone code, certificate text, received at, lead ref, row number), numbers in memory only.
    Returns how many certificates were queued."""
    client, made, queued = upload.client, set(), 0
    for number, token, text, received_at, lead_ref, row in rows:
        for claim in claims_for(client, text, received_at):
            queued += 1
            match_now(claim, number, token)
            _save(client, token, claim.cert_created_at or received_at, made, kind=ConsentProof.Kind.CERTIFICATE, proof_type='web_cert',
                  certificate=claim, date_known=bool(claim.cert_created_at), source_system=SOURCE,
                  source_record_id=f'upload {upload.pk} row {row}', lead_id=lead_ref, source_hint='VENDOR_LEAD_FILE')
    return queued
