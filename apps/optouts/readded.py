"""M34: opted-out numbers that came back in an uploaded list (bulk import or small batch), before that list."""
from apps.access_log.recorder import record
from apps.imports.models import CrmCreation, ImportBatch

from .models import OptOutEvent, ReaddedNumber

UPLOADS = [ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL]


def check_batches(client) -> int:
    """Marks each upload with how many numbers in it had opted out earlier. Returns the client's new finds."""
    new = 0
    for batch in ImportBatch.objects.filter(client=client, kind__in=UPLOADS):
        readded, found_now = set(), 0
        for creation in CrmCreation.objects.filter(batch=batch):
            for token in creation.phone_tokens:
                earlier = OptOutEvent.objects.filter(client=client, phone_token=token, at__lt=creation.created_at).order_by('at').first()
                if earlier is None:
                    continue
                readded.add(token)
                _, made = ReaddedNumber.objects.get_or_create(
                    client=client, source_system=creation.source_system, record_id=creation.record_id, phone_token=token,
                    defaults={'record_created_at': creation.created_at, 'opted_out_at': earlier.at})
                found_now += made
        if len(readded) != batch.opted_out_readded:
            batch.opted_out_readded = len(readded)
            batch.save(update_fields=['opted_out_readded'])
        new += found_now
        if found_now:  # logged once, when first found (batches are rebuilt every 15 minutes)
            record('optout_readded', client_id=client.pk, object=f'{batch} brought back {len(readded)} opted-out number(s)'[:254])
    return new
