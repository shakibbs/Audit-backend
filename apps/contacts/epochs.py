"""Phone epochs: the timeline of owners of one number. Every contact belongs to the epoch it happened in. A signal
("the owner changed on date X") splits the timeline; later contacts move to the new epoch. Nothing is deleted.

Signals now: a number that MOVED between CRM customer records. Later: "wrong number" replies (Module 9), the client's
reassigned-number results, a new consent from someone else (Module 6) — each calls split()."""
from django.db import transaction

from .models import ContactEvent, CrmPhoneHolder, PhoneEpoch


def _epochs(client_id, token):
    return list(PhoneEpoch.objects.select_for_update().filter(client_id=client_id, phone_token=token).order_by('number'))


def _contains(epoch: PhoneEpoch, at) -> bool:
    return (epoch.started_at is None or epoch.started_at <= at) and (epoch.ended_at is None or at < epoch.ended_at)


def epoch_for(client_id, token, at) -> PhoneEpoch:
    with transaction.atomic():
        epochs = _epochs(client_id, token)
        if not epochs:
            return PhoneEpoch.objects.create(client_id=client_id, phone_token=token, number=1, reason=PhoneEpoch.Reason.FIRST_SEEN)
        return next((e for e in epochs if _contains(e, at)), epochs[-1])


def attach(contact: ContactEvent) -> None:
    epoch = epoch_for(contact.client_id, contact.phone_token, contact.occurred_at)
    if contact.epoch_id != epoch.pk:
        ContactEvent.objects.filter(pk=contact.pk).update(epoch=epoch)
        contact.epoch = epoch


def split(client_id, token, at, reason: str, source: str = '') -> PhoneEpoch:
    """A new owner from `at`. Returns the epoch starting at `at` (an existing one if it already starts there)."""
    with transaction.atomic():
        epochs = _epochs(client_id, token) or [PhoneEpoch.objects.create(client_id=client_id, phone_token=token, number=1,
                                                                         reason=PhoneEpoch.Reason.FIRST_SEEN)]
        current = next((e for e in epochs if _contains(e, at)), epochs[-1])
        if current.started_at == at:
            return current
        new = PhoneEpoch(client_id=client_id, phone_token=token, number=0, started_at=at, ended_at=current.ended_at,
                         reason=reason, signal_source=source)
        current.ended_at = at
        current.save(update_fields=['ended_at'])
        ordered = sorted([*epochs, new], key=lambda e: (e.started_at is not None, e.started_at))
        for i, e in enumerate(ordered, 1):  # renumber in time order (two passes keep the unique numbers apart)
            e.number = 1000 + i
            e.save()
        for e in ordered:
            e.number -= 1000
            e.save(update_fields=['number'])
        moving = ContactEvent.objects.filter(client_id=client_id, phone_token=token, occurred_at__gte=at)
        if new.ended_at:
            moving = moving.filter(occurred_at__lt=new.ended_at)
        moving.update(epoch=new)
        return new


def crm_record_seen(client, connection, record, phone_tokens) -> None:
    """Hand-off receiver for CRM people and leads: notices a number moving to a different customer record."""
    if record.content_kind not in ('lead', 'crm_record') or record.source_record_id.startswith('calls:'):
        return
    source, rid, at, now_held = connection.provider, record.source_record_id, record.changed_at, set(phone_tokens)
    with transaction.atomic():
        mine = CrmPhoneHolder.objects.select_for_update().filter(client=client, source_system=source, record_id=rid, released_at__isnull=True)
        for holder in mine:
            if holder.phone_token not in now_held:  # this record no longer has the number
                holder.released_at = at
                holder.save(update_fields=['released_at'])
        already = {h.phone_token for h in mine if h.phone_token in now_held}
        for token in now_held - already:
            others = CrmPhoneHolder.objects.filter(client=client, source_system=source, phone_token=token).exclude(record_id=rid)
            moved = others.exists() and not others.filter(released_at__isnull=True).exists()
            CrmPhoneHolder.objects.create(client=client, source_system=source, record_id=rid, phone_token=token, held_from=at)
            if moved:  # every earlier record let go of it, and a different record now has it: a new owner
                split(client.pk, token, at, PhoneEpoch.Reason.CRM_MOVED, source)
