"""M34: opted-out numbers that came back in an uploaded list (bulk import or small batch), before that list."""
from apps.access_log.recorder import record
from apps.imports.models import CrmCreation, CrmUpdate, DialerListEntry, ImportBatch

from .models import OptOutEvent, ReaddedNumber

UPLOADS = [ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL]


def entries(batch):
    """(tool, record ID, time, phone codes) for each record in an upload: created, updated (Module 8) or put in a dialer list."""
    if batch.system == 'crm_update':
        for u in CrmUpdate.objects.filter(batch=batch):
            yield u.source_system, f'{u.record_id}@{u.updated_at:%Y%m%dT%H%M%S}', u.updated_at, u.phone_tokens
    elif batch.system == 'dialer':
        for e in DialerListEntry.objects.filter(batch=batch):
            yield e.source_system, f'list {e.list_id} lead {e.lead_id}', e.added_at, [e.phone_token]
    else:
        for c in CrmCreation.objects.filter(batch=batch):
            yield c.source_system, c.record_id, c.created_at, c.phone_tokens


def check_batches(client) -> int:
    """Marks each upload with how many numbers in it had opted out earlier. Returns the client's new finds."""
    new = 0
    for batch in ImportBatch.objects.filter(client=client, kind__in=UPLOADS):
        readded, found_now = set(), 0
        for source, record_id, at, tokens in entries(batch):
            for token in tokens:
                earlier = OptOutEvent.objects.filter(client=client, phone_token=token, at__lt=at).order_by('at').first()
                if earlier is None:
                    continue
                readded.add(token)
                _, made = ReaddedNumber.objects.get_or_create(
                    client=client, source_system=source, record_id=record_id, phone_token=token,
                    defaults={'record_created_at': at, 'opted_out_at': earlier.at})
                found_now += made
        if len(readded) != batch.opted_out_readded:
            batch.opted_out_readded = len(readded)
            batch.save(update_fields=['opted_out_readded'])
        new += found_now
        if found_now:  # logged once, when first found (batches are rebuilt every 15 minutes)
            record('optout_readded', client_id=client.pk, object=f'{batch} brought back {len(readded)} opted-out number(s)'[:254])
    return new
