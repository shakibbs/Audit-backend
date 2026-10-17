"""Keeping results up to date (spec §5 engineering notes):
- something new (a proof, a read certificate, a late STOP, a new owner, a rule change) queues a Recheck of just the
  contacts it can change; worked through in batches every minute, each change saved in the history with its reason;
- time-dependent results (a certificate about to expire) are checked again every night;
- a record a result stood on that changed or was deleted freezes the result: never recomputed, left out of totals.
"""
from datetime import timedelta

from django.utils import timezone

from apps.contacts.epochs import epoch_for
from apps.contacts.models import ContactEvent
from apps.rulebook.lookup import RuleSet
from apps.tenancy.scope import all_clients

from .models import ConsentProof, ConsentResult, Recheck, ResultChange

BATCH = 1000  # contacts checked again per minute
SKEW = timedelta(minutes=2)  # a proof can cover contacts up to the clock tolerance before it


def queue(client_id, phone_token: str, from_at, reason: str, to_at=None) -> None:
    """Check again from `from_at` (None = the beginning). Merges into a waiting one for the same number and reason."""
    waiting = Recheck.objects.filter(client_id=client_id, phone_token=phone_token, reason=reason, after_contact=0, to_at=to_at).first()
    if waiting:
        if waiting.from_at is not None and (from_at is None or from_at < waiting.from_at):
            Recheck.objects.filter(pk=waiting.pk).update(from_at=from_at)
        return
    Recheck.objects.create(client_id=client_id, phone_token=phone_token, from_at=from_at, to_at=to_at, reason=reason)


def inputs_of(contact) -> dict:
    """The facts a result stands on. A later change to any of them freezes it (the owner epoch is not one: a new owner
    is a reason to check again)."""
    return {'phone_token': contact.phone_token, 'occurred_at': contact.occurred_at.isoformat(), 'channel': contact.channel,
            'direction': contact.direction, 'dial_mode': contact.dial_mode, 'lead_id': contact.lead_id}


def note_change(result: ConsentResult, old_status: str, old_code: str, reason: str) -> None:
    if (old_status, old_code) != (result.status, result.primary_code):
        ResultChange.objects.create(client_id=result.client_id, contact_id=result.contact_id, variant=result.variant, old_status=old_status,
                                    new_status=result.status, old_code=old_code, new_code=result.primary_code, reason=reason)


def freeze(results, reason: str) -> int:
    count = 0
    for result in results.filter(frozen=False):
        result.frozen, result.frozen_reason, result.frozen_at = True, reason, timezone.now()
        result.save(update_fields=['frozen', 'frozen_reason', 'frozen_at'])
        ResultChange.objects.create(client_id=result.client_id, contact_id=result.contact_id, variant=result.variant, old_status=result.status,
                                    new_status=result.status, old_code=result.primary_code, new_code=reason, reason='frozen')
        count += 1
    return count


def using_proof(proof_id: int):
    return ConsentResult.objects.filter(bases__contains=[{'proof': proof_id}])


# --- what queues a recheck ---------------------------------------------------------------------------------------------

def proof_saved(proof: ConsentProof, created: bool, old_when=None) -> None:
    when = proof.when()
    starts = [w for w in (when, old_when) if w is not None]
    queue(proof.client_id, proof.phone_token, min(starts) - SKEW if starts else None, 'new_proof' if created else 'certificate_read')


def optout_saved(sender, instance, created, **kwargs) -> None:
    if created:
        queue(instance.client_id, instance.phone_token, instance.at, 'late_opt_out')


def epoch_saved(sender, instance, created, **kwargs) -> None:
    if created and instance.started_at is not None:
        # Proofs belong to the owner on their own date: move the ones dated in the new owner's time, then check again.
        for proof in ConsentProof.objects.filter(client_id=instance.client_id, phone_token=instance.phone_token):
            right = epoch_for(instance.client_id, instance.phone_token, proof.when()) if proof.when() else None
            if right and proof.epoch_id != right.pk:
                ConsentProof.objects.filter(pk=proof.pk).update(epoch=right)
        queue(instance.client_id, instance.phone_token, instance.started_at, 'owner_changed')


def rules_changed(sender, from_date=None, **kwargs) -> None:
    from datetime import datetime, time, timezone as tz
    start = datetime.combine(from_date, time(0), tzinfo=tz.utc) if from_date else None
    with all_clients():
        queue(None, '', start, 'rule_changed')


# --- freezing ----------------------------------------------------------------------------------------------------------

def contact_seen(client, connection, record, phone_tokens) -> None:
    """Hand-off receiver (after the normalizer): the record of a checked contact came back changed → freeze if the
    facts its result stood on are different now."""
    contact = ContactEvent.objects.filter(client=client, source_system=connection.provider, source_record_id=record.source_record_id).first()
    if contact is None:
        return
    now = inputs_of(contact)
    changed = [r.pk for r in ConsentResult.objects.filter(contact=contact, frozen=False) if r.inputs and r.inputs != now]
    if changed:
        freeze(ConsentResult.objects.filter(pk__in=changed), 'FZ_INPUTS_CHANGED')


def withdraw(proofs, reason: str) -> None:
    for proof in proofs.filter(withdrawn_at__isnull=True):
        ConsentProof.objects.filter(pk=proof.pk).update(withdrawn_at=timezone.now())
        freeze(using_proof(proof.pk), reason)


def records_seen(client, connection, record_ids: list[str]) -> None:
    """Weekly full check: these records still exist in the tool."""
    now = timezone.now()
    ConsentResult.objects.filter(client=client, contact__source_system=connection.provider,
                                 contact__source_record_id__in=record_ids).update(source_seen_at=now)
    ConsentProof.objects.filter(client=client, source_system=connection.provider, source_record_id__in=record_ids).update(source_seen_at=now)


def sweep_done(connection, started_at) -> None:
    """The weekly full check read every record: what it did not find was deleted from the tool → freeze."""
    if started_at is None:
        return  # a full check that began before CiV noted its start: nothing can be concluded
    gone = ConsentResult.objects.filter(client_id=connection.client_id, contact__source_system=connection.provider,
                                        contact__created_at__lt=started_at).exclude(source_seen_at__gte=started_at)
    freeze(gone, 'FZ_SOURCE_DELETED')
    withdraw(ConsentProof.objects.filter(client_id=connection.client_id, source_system=connection.provider, created_at__lt=started_at)
             .exclude(source_seen_at__gte=started_at), 'FZ_SOURCE_DELETED')


# --- working through the queue -------------------------------------------------------------------------------------------

def recheck_contact(contact, rules, reason: str, as_of=None) -> None:
    from .checks import check_contact
    from .needs import work_out
    if ConsentResult.objects.filter(contact=contact, frozen=True).exists():
        return  # frozen: never recomputed
    work_out(contact, rules)  # what is needed can change too (a STOP in force, a rule)
    check_contact(contact, rules, as_of=as_of, reason=reason)


def run_rechecks(limit: int = BATCH) -> int:
    """One batch of queued rechecks, oldest first; a long one carries on next minute from where it stopped."""
    rules, done = RuleSet(), 0
    for job in Recheck.objects.all()[:20]:
        contacts = ContactEvent.objects.filter(is_primary=True, pk__gt=job.after_contact, consent_results__isnull=False).distinct()
        if job.client_id:
            contacts = contacts.filter(client_id=job.client_id)
        if job.phone_token:
            contacts = contacts.filter(phone_token=job.phone_token)
        if job.from_at:
            contacts = contacts.filter(occurred_at__gte=job.from_at)
        if job.to_at:
            contacts = contacts.filter(occurred_at__lt=job.to_at)
        want = limit - done
        batch = list(contacts.select_related('client', 'epoch').order_by('pk')[:want])
        for contact in batch:
            recheck_contact(contact, rules, job.reason)
        done += len(batch)
        if len(batch) < want:
            job.delete()  # finished
        else:
            Recheck.objects.filter(pk=job.pk).update(after_contact=batch[-1].pk)
            break  # the batch is full: carry on next minute
    return done


def recheck_pending(limit: int = BATCH) -> int:
    """Pending results whose certificate has since been read (claimed, lost or not found)."""
    rules = RuleSet()
    results = (ConsentResult.objects.filter(status=ConsentResult.Status.PENDING, frozen=False)
               .exclude(proof__certificate__state__in=['waiting', 'no_key']).select_related('contact__client', 'contact__epoch'))
    contacts = {r.contact_id: r.contact for r in results[:limit]}
    for contact in contacts.values():
        recheck_contact(contact, rules, 'certificate_read')
    return len(contacts)


def recheck_time_passed(limit: int = 5000) -> int:
    """Nightly: results that stood on a certificate now expiring within the warning days."""
    rules = RuleSet()
    warning = timedelta(days=int(rules.get('cert_expiry_warning_days', on=timezone.localdate()).value or 30))
    soon = timezone.now() + warning
    results = (ConsentResult.objects.filter(status=ConsentResult.Status.VERIFIED, frozen=False, proof__certificate__cert_expires_at__lte=soon)
               .select_related('contact__client', 'contact__epoch'))
    contacts = {r.contact_id: r.contact for r in results[:limit]}
    for contact in contacts.values():
        recheck_contact(contact, rules, 'time_passed')
    return len(contacts)
