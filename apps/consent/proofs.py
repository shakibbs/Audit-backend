"""Collects proofs of permission from every synced record, and builds each number's evidence folder.

- A certificate link (TrustedForm / Jornaya) in a lead, CRM or dialer record → a certificate proof for each number in
  that record, tied to the certificate's claim (its creation time is the consent time once claimed).
- A CRM field named for consent and set to yes → self-asserted (spec: never enough on its own).
- HubSpot "became a customer" date → existing-customer purchase.
- Proofs belong to the owner (epoch) of the number on the consent date: owner 1's proof never covers owner 2.
"""
import json
from datetime import UTC, datetime

from django.db import IntegrityError, transaction

from apps.certificates.models import CertificateClaim
from apps.certificates.scan import found_in
from apps.contacts.epochs import epoch_for

from .models import ConsentProof
from .sources import hint_from_record

YES = {True, 'true', 'yes', 'y', '1', 'on', 'consented', 'opted in', 'opted_in'}


def _when(value) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, UTC)
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00').replace('+0000', '+00:00'))
    except ValueError:
        return None


def consent_fields(provider: str, row: dict) -> bool:
    """True when a field named for consent (not opt-out) says yes."""
    fields = row.get('properties', {}) if provider == 'hubspot' else row
    for name, value in fields.items():
        lowered = name.lower()
        if 'consent' in lowered and 'opt' not in lowered and 'revok' not in lowered:
            if value in YES or str(value).strip().lower() in YES:
                return True
    return False


def _save(client, token, at, made: set, **fields) -> None:
    """Saves one proof; a new one, or one whose date changed, queues a recheck of that number from its date."""
    from .keeping import freeze, proof_saved, using_proof
    epoch = epoch_for(client.pk, token, at) if at else None
    key = dict(client=client, phone_token=token, source_system=fields.pop('source_system'), source_record_id=fields.pop('source_record_id'),
               kind=fields.pop('kind'), certificate=fields.pop('certificate', None))
    old = ConsentProof.objects.filter(**key).first()
    if old and key['kind'] == ConsentProof.Kind.SELF_ASSERTED:
        at = old.captured_at  # a CRM box keeps the date CiV first saw it; editing the record elsewhere does not move it
    try:
        with transaction.atomic():
            proof, created = ConsentProof.objects.update_or_create(**key, defaults={**fields, 'epoch': epoch, 'captured_at': at, 'withdrawn_at': None})
    except IntegrityError:
        return
    made.add(proof.pk)
    if created:
        proof_saved(proof, True)
    elif old.captured_at != at and old.date_known and fields.get('date_known', True):
        freeze(using_proof(proof.pk), 'FZ_INPUTS_CHANGED')  # the record now gives another date: results that used it stay as they were
        proof_saved(proof, False, old.when())


def proofs_seen(client, connection, record, phone_tokens) -> None:
    from .keeping import withdraw
    tokens = [t for t in phone_tokens if t]
    try:
        row = json.loads(record.raw)
    except ValueError:
        row = {}
    source, rid = connection.provider, record.source_record_id
    made: set = set()
    hint = hint_from_record(source, row)
    lead_id = str(row.get('lead_id') or row.get('Id') or row.get('id') or '')
    for provider, ref in found_in(record.raw):
        claim = CertificateClaim.objects.filter(client=client, provider=provider, cert_ref=ref).first()
        if claim is None:
            continue
        at = claim.cert_created_at or record.changed_at
        for token in tokens:
            _save(client, token, at, made, kind=ConsentProof.Kind.CERTIFICATE, proof_type='web_cert', certificate=claim,
                  date_known=bool(claim.cert_created_at), source_system=source, source_record_id=rid, lead_id=lead_id, source_hint=hint)
    if record.content_kind in ('lead', 'crm_record') and not rid.startswith('calls:'):
        if consent_fields(source, row):
            for token in tokens:
                _save(client, token, record.changed_at, made, kind=ConsentProof.Kind.SELF_ASSERTED, proof_type='crm_flag',
                      source_system=source, source_record_id=rid, lead_id=lead_id, source_hint=hint)
        customer_since = _when(row.get('properties', {}).get('hs_lifecyclestage_customer_date')) if source == 'hubspot' else None
        if customer_since:
            for token in tokens:
                _save(client, token, customer_since, made, kind=ConsentProof.Kind.EBR_PURCHASE, proof_type='purchase',
                      source_system=source, source_record_id=rid, lead_id=lead_id, source_hint=hint)
    from apps.provenance.evidence import found as evidence_in
    for item in evidence_in(client, connection, record, row, tokens):  # no certificate needed: the person acted first
        _save(client, item['phone_token'], item['at'], made, kind=item['kind'], proof_type=item['kind'],
              source_system=source, source_record_id=rid, lead_id=lead_id, source_hint=hint)
    # The record came back without a proof it gave before (link removed, box unticked, number changed): withdraw it.
    withdraw(ConsentProof.objects.filter(client=client, source_system=source, source_record_id=rid).exclude(pk__in=made), 'FZ_INPUTS_CHANGED')


def refresh_certificate_dates() -> int:
    """Once a certificate is claimed, its proofs take its real creation time and the right owner epoch."""
    from .keeping import proof_saved
    fixed = 0
    for proof in ConsentProof.objects.filter(kind=ConsentProof.Kind.CERTIFICATE, date_known=False,
                                             certificate__cert_created_at__isnull=False).select_related('certificate'):
        old_when = proof.captured_at
        proof.captured_at, proof.date_known = proof.certificate.cert_created_at, True
        proof.epoch = epoch_for(proof.client_id, proof.phone_token, proof.captured_at)
        proof.save(update_fields=['captured_at', 'date_known', 'epoch', 'updated_at'])
        proof_saved(proof, False, old_when)  # check that number again with the real date
        fixed += 1
    return fixed


def evidence_folder(client, phone_token: str, epoch) -> dict:
    """Everything CiV holds for one owner of one number: proofs, and whether the number came from an upload."""
    from apps.imports.batches import origin
    proofs = list(ConsentProof.objects.filter(client=client, phone_token=phone_token, epoch=epoch, withdrawn_at__isnull=True).select_related('certificate'))
    first_contact = epoch.contacts.order_by('occurred_at').first() if epoch else None
    batch = origin(client, phone_token, first_contact.occurred_at) if first_contact else None
    return {'proofs': proofs, 'import_batch': batch,
            'manual_import_no_evidence': bool(batch and batch.kind in ('bulk_import', 'small_batch')
                                              and not any(p.kind != ConsentProof.Kind.SELF_ASSERTED for p in proofs))}
