"""Proof requests (spec §5a): for each uploaded list, a fixed random sample of contacted numbers with no evidence
(50; 100 when the list has over 10,000 records). The client attaches a file or says "none"; CiV staff check the file
(owner decision: CiV keeps it to read it; Document AI later). Proof rate = valid proofs ÷ requested, per list."""
import hashlib
import random
from datetime import timedelta

from django.utils import timezone

from apps.consent.keeping import queue
from apps.consent.models import ConsentProof
from apps.contacts.models import ContactEvent
from apps.imports.models import CrmCreation, CrmUpdate, DialerListEntry, ImportBatch

from .models import ProofRequest

SAMPLE, BIG_SAMPLE, BIG_LIST = 50, 100, 10_000
ANSWER_DAYS = 30
KEEP_YEARS = 4
UPLOADS = (ImportBatch.Kind.BULK, ImportBatch.Kind.SMALL)
EVIDENCE = [k for k in ConsentProof.Kind.values if k not in (ConsentProof.Kind.SELF_ASSERTED, ConsentProof.Kind.CLIENT_SUPPLIED)]


def batch_key(batch: ImportBatch) -> str:
    who = batch.list_id if batch.system == 'dialer' else batch.created_by
    return f'{batch.system}|{batch.source_system}|{who}|{batch.starts:%Y%m%dT%H%M%S}'


def batch_label(batch: ImportBatch) -> str:
    what = {'crm_update': 'Update upload', 'dialer': f'Dialer upload · list {batch.list_id}'}.get(batch.system, 'Uploaded list')
    size = batch.updated_count if batch.system == 'crm_update' else batch.created_count
    return f'{what} · {size:,} records · {batch.starts:%d %b %Y}'


def tokens_of(batch: ImportBatch) -> list[str]:
    if batch.system == 'crm_update':
        rows = CrmUpdate.objects.filter(batch=batch).values_list('phone_tokens', flat=True)
    elif batch.system == 'dialer':
        return sorted(set(DialerListEntry.objects.filter(batch=batch).values_list('phone_token', flat=True)))
    else:
        rows = CrmCreation.objects.filter(batch=batch).values_list('phone_tokens', flat=True)
    return sorted({t for tokens in rows for t in tokens})


def send(client) -> int:
    """Samples each uploaded list once (the same numbers every time, from the list's own key)."""
    made = 0
    for batch in ImportBatch.objects.filter(client=client, kind__in=UPLOADS):
        key = batch_key(batch)
        if ProofRequest.objects.filter(client=client, batch_key=key).exists():
            continue
        tokens = tokens_of(batch)
        called = set(ContactEvent.objects.filter(client=client, phone_token__in=tokens, direction='outbound').values_list('phone_token', flat=True))
        proven = set(ConsentProof.objects.filter(client=client, phone_token__in=called, kind__in=EVIDENCE, withdrawn_at__isnull=True)
                     .values_list('phone_token', flat=True))
        pool = sorted(called - proven)
        if not pool:
            continue  # nothing to ask yet (no number called, or all have evidence)
        size = BIG_SAMPLE if len(tokens) > BIG_LIST else SAMPLE
        seed = int(hashlib.sha256(f'{client.pk}|{key}'.encode()).hexdigest()[:12], 16)
        picked = random.Random(seed).sample(pool, min(size, len(pool)))
        labels = dict(ContactEvent.objects.filter(client=client, phone_token__in=picked).values_list('phone_token', 'masked_label'))
        due = timezone.now() + timedelta(days=ANSWER_DAYS)
        ProofRequest.objects.bulk_create([ProofRequest(client=client, batch_key=key, batch_label=batch_label(batch), batch_size=len(tokens),
                                                       phone_token=t, masked_label=labels.get(t, ''), due_at=due) for t in picked],
                                         ignore_conflicts=True)
        made += len(picked)
    return made + send_lead_files(client)


def send_lead_files(client) -> int:
    """Vendor lead files (Module 12): leads with no consent link and no other proof, called, sampled the same way."""
    from apps.uploads.models import Source, UploadedFile
    made = 0
    for upload in UploadedFile.objects.filter(client=client, source=Source.VENDOR_LEADS):
        key = f'leadfile|{upload.pk}'
        if ProofRequest.objects.filter(client=client, batch_key=key).exists():
            continue
        tokens = set(upload.vendor_lead_rows.values_list('phone_token', flat=True))
        called = set(ContactEvent.objects.filter(client=client, phone_token__in=tokens, direction='outbound').values_list('phone_token', flat=True))
        proven = set(ConsentProof.objects.filter(client=client, phone_token__in=called, kind__in=EVIDENCE, withdrawn_at__isnull=True)
                     .values_list('phone_token', flat=True))
        pool = sorted(called - proven)
        if not pool:
            continue
        size = BIG_SAMPLE if len(tokens) > BIG_LIST else SAMPLE
        seed = int(hashlib.sha256(f'{client.pk}|{key}'.encode()).hexdigest()[:12], 16)
        picked = random.Random(seed).sample(pool, min(size, len(pool)))
        labels = dict(ContactEvent.objects.filter(client=client, phone_token__in=picked).values_list('phone_token', 'masked_label'))
        label = f'Vendor lead file · {len(tokens):,} lead{"" if len(tokens) == 1 else "s"} · {upload.received_at:%d %b %Y}'
        due = timezone.now() + timedelta(days=ANSWER_DAYS)
        ProofRequest.objects.bulk_create([ProofRequest(client=client, batch_key=key, batch_label=label, batch_size=len(tokens), phone_token=t,
                                                       masked_label=labels.get(t, ''), due_at=due) for t in picked], ignore_conflicts=True)
        made += len(picked)
    return made


def rates(client) -> list[dict]:
    """Per uploaded list: asked, answered, proofs attached, checked valid, "none", overdue, and the proof rate."""
    now, out = timezone.now(), []
    for key in ProofRequest.objects.filter(client=client).values_list('batch_key', flat=True).distinct():
        rows = list(ProofRequest.objects.filter(client=client, batch_key=key))
        valid = sum(1 for r in rows if r.review == ProofRequest.Review.VALID)
        out.append({'batchKey': key, 'label': rows[0].batch_label, 'listSize': rows[0].batch_size, 'asked': len(rows),
                    'attached': sum(1 for r in rows if r.answer == ProofRequest.Answer.PROOF),
                    'valid': valid, 'waitingReview': sum(1 for r in rows if r.answer == ProofRequest.Answer.PROOF and not r.review),
                    'none': sum(1 for r in rows if r.answer == ProofRequest.Answer.NONE),
                    'overdue': sum(1 for r in rows if not r.answer and r.due_at < now),
                    'rate': round(valid / len(rows), 3) if rows else None})
    return out


def answer(request: ProofRequest, user, *, none: bool = False, upload=None, file_type: str = '') -> None:
    """The client's answer. A file becomes a client-supplied proof, weak until a CiV staff member checks it."""
    now = timezone.now()
    request.answered_at, request.answered_by = now, user
    if none:
        request.answer = ProofRequest.Answer.NONE
        request.save()
        ConsentProof.objects.filter(proof_request=request).delete()
    else:
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        request.answer, request.file_type, request.original_name = ProofRequest.Answer.PROOF, file_type, upload.name[:255]
        request.file_sha256, request.review, request.consent_date = digest.hexdigest(), ProofRequest.Review.WAITING, None
        request.file.save(upload.name, upload, save=False)
        request.save()
        from apps.contacts.epochs import epoch_for
        ConsentProof.objects.update_or_create(  # for the owner the request was about (the number's owner when asked)
            client=request.client, phone_token=request.phone_token, kind=ConsentProof.Kind.CLIENT_SUPPLIED, proof_request=request,
            source_system='client', source_record_id=f'proof-request-{request.pk}',
            defaults={'proof_type': 'client_unchecked', 'captured_at': None, 'date_known': False, 'withdrawn_at': None,
                      'epoch': epoch_for(request.client_id, request.phone_token, request.sent_at)})
    queue(request.client_id, request.phone_token, None, 'new_proof')


def review(request: ProofRequest, staff_email: str, *, valid: bool, consent_date=None, note: str = '') -> None:
    """A CiV staff member's check of the file. Valid: a real proof dated `consent_date` (a signed form counts as signed
    written consent). Not valid: the proof is removed and the number's calls are checked again."""
    from apps.contacts.epochs import epoch_for
    request.review = ProofRequest.Review.VALID if valid else ProofRequest.Review.INVALID
    request.consent_date, request.review_note = consent_date if valid else None, note[:300]
    request.reviewed_by, request.reviewed_at = staff_email, timezone.now()
    request.save()
    proofs = ConsentProof.objects.filter(proof_request=request)
    if valid:
        from datetime import datetime, time, timezone as tz
        at = datetime.combine(consent_date, time(23, 59, 59), tzinfo=tz.utc)  # the end of that day: never earlier than shown
        kind = {'signed_form': 'signed_form', 'recording': 'verbal_recording'}.get(request.file_type, 'client_document')
        proofs.update(proof_type=kind, captured_at=at, date_known=True, epoch=epoch_for(request.client_id, request.phone_token, at))
    else:
        proofs.delete()
    queue(request.client_id, request.phone_token, None, 'new_proof')


def purge_old(now=None) -> int:
    """Files older than 4 years are deleted; the fingerprint and the review stay."""
    now = now or timezone.now()
    count = 0
    from apps.evidence.holds import Holds
    holds = Holds()
    for request in ProofRequest.objects.filter(answered_at__lt=now - timedelta(days=365 * KEEP_YEARS + 1), purged_at__isnull=True).exclude(file=''):
        if holds.covers(request.client_id, request.answered_at, [request.phone_token]):
            continue  # under a legal hold (Module 14)
        request.file.delete(save=False)
        ProofRequest.objects.filter(pk=request.pk).update(file='', purged_at=now)
        count += 1
    return count
