"""The provenance ladder (spec §5a): for each contacted number (per owner), the latest lead record received at or
before the first outbound contact, then the first rung that matches, strongest first:
1 lead platform feed (no reader yet: never matches) · 2 the CRM names a vendor · 3 vendor invoice (skipped: API only)
· 4 the certificate's website · 5 an uploaded list (Module 5 batch) · 6 untraced.
"""
from urllib.parse import urlsplit

from django.db.models import Min

from apps.consent.models import ConsentProof
from apps.consent.sources import CLIENT_FORM, source_of
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation, CrmUpdate, DialerListEntry, ImportBatch

from .models import Provenance

B = Provenance.Basis
UPLOADS = (ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL)


def first_contacts(client):
    """(phone code, owner epoch) → its first outbound counted contact."""
    rows = (ContactEvent.objects.filter(client=client, direction='outbound', is_primary=True, is_test=False)
            .values('phone_token', 'epoch_id').annotate(first=Min('occurred_at')))
    for row in rows:
        contact = (ContactEvent.objects.filter(client=client, phone_token=row['phone_token'], epoch_id=row['epoch_id'],
                                               direction='outbound', is_primary=True, occurred_at=row['first']).order_by('pk').first())
        yield row['phone_token'], row['epoch_id'], contact


def website(page: str) -> str:
    host = urlsplit(f'//{page}').hostname or ''
    return host.removeprefix('www.')


def upload_name(batch) -> str:
    where = {'crm_update': 'Update upload', 'dialer': f'Dialer upload · list {batch.list_id}'}.get(batch.system, batch.get_kind_display())
    return f'{where} · {batch.starts:%d %b %Y}'


def upload_before(client, token: str, lead, at):
    """The upload the number arrived by before the first contact: the lead's own creation batch, a sheet that
    re-touched its record (update upload), or a dialer list with no CRM record."""
    if lead and lead.batch and lead.batch.kind in UPLOADS:
        return lead.batch
    update = (CrmUpdate.objects.filter(client=client, phone_tokens__contains=[token], updated_at__lte=at, batch__kind__in=UPLOADS)
              .select_related('batch').order_by('-updated_at').first())
    if update:
        return update.batch
    if lead is None:
        entry = (DialerListEntry.objects.filter(client=client, phone_token=token, added_at__lte=at, batch__kind__in=UPLOADS)
                 .select_related('batch').order_by('-added_at').first())
        return entry.batch if entry else None
    return None


def climb(client, token: str, epoch_id, contact) -> dict:
    lead = (CrmCreation.objects.filter(client=client, phone_tokens__contains=[token], created_at__lte=contact.occurred_at)
            .select_related('batch').order_by('-created_at').first())
    found = {'lead_system': lead.source_system if lead else '', 'lead_record_id': lead.record_id if lead else '',
             'lead_received_at': lead.created_at if lead else None, 'batch': lead.batch if lead else None,
             'source_name': '', 'own_website': False, 'note': ''}
    if lead and lead.vendor:
        return {**found, 'basis': B.CRM_FIELD, 'source_name': lead.vendor}
    proofs = (ConsentProof.objects.filter(client=client, phone_token=token, certificate__isnull=False, withdrawn_at__isnull=True,
                                          captured_at__lte=contact.occurred_at).exclude(certificate__page='')
              .select_related('certificate').order_by('-captured_at'))
    if epoch_id:
        proofs = proofs.filter(epoch_id=epoch_id)
    if lead:  # prefer the certificate that came with the lead used
        proofs = sorted(proofs, key=lambda p: (p.source_record_id != lead.record_id,))
    proof = next(iter(proofs), None)
    if proof:
        return {**found, 'basis': B.CERT_DOMAIN, 'source_name': website(proof.certificate.page), 'own_website': source_of(proof) == CLIENT_FORM}
    upload = upload_before(client, token, lead, contact.occurred_at)
    if upload:
        return {**found, 'basis': B.MANUAL_IMPORT, 'batch': upload, 'source_name': upload_name(upload)}
    if lead and lead.batch and lead.batch.kind == ImportBatch.Kind.FEED:
        found['note'] = 'Arrived by an automatic feed; the record names no vendor.'
    elif lead:
        found['note'] = 'The CRM record names no vendor and carries no certificate.'
    else:
        found['note'] = 'No CRM record before the first contact.'
    return {**found, 'basis': B.UNTRACED}


def rebuild(client) -> int:
    count = 0
    for token, epoch_id, contact in first_contacts(client):
        if contact is None:
            continue
        found = climb(client, token, epoch_id, contact)
        Provenance.objects.update_or_create(client=client, phone_token=token, epoch_id=epoch_id, defaults={
            **found, 'first_contact': contact, 'first_contact_at': contact.occurred_at})
        count += 1
    return count


def untraced(client, month_start, month_end) -> list[dict]:
    """The month's untraced numbers for the client: masked label and the CRM record to look up, never the number."""
    rows = (Provenance.objects.filter(client=client, basis=B.UNTRACED, first_contact_at__date__gte=month_start,
                                      first_contact_at__date__lte=month_end).select_related('first_contact').order_by('first_contact_at'))
    return [{'number': r.first_contact.masked_label if r.first_contact else '', 'firstContactAt': r.first_contact_at,
             'tool': r.first_contact.source_system if r.first_contact else '', 'crmRecord': f'{r.lead_system} {r.lead_record_id}'.strip(),
             'note': r.note} for r in rows]
