"""What an upload changes: numbers on the internal list or in DNC check records are checked again by the consent
engine (their "what proof is needed" depends on it)."""
from apps.consent.keeping import queue

from .models import Source


def tokens_of(upload) -> set[str]:
    if upload.source == Source.INTERNAL_LIST:
        return set(upload.internal_entries.values_list('phone_token', flat=True))
    if upload.source == Source.DNC_CHECKS:
        return set(upload.dnc_rows.values_list('phone_token', flat=True))
    return set()


def after_upload(upload) -> None:
    for token in tokens_of(upload):
        queue(upload.client_id, token, None, 'new_proof')


def purge_old(now=None) -> int:
    """Files older than 4 years: the file is deleted; its fingerprint and the rows read from it stay."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import UploadedFile
    now = now or timezone.now()
    count = 0
    from apps.evidence.holds import Holds
    from apps.vendors.rates import vendor_key
    holds = Holds()
    for upload in UploadedFile.objects.filter(received_at__lt=now - timedelta(days=365 * 4 + 1), purged_at__isnull=True).exclude(file=''):
        tokens = set(tokens_of(upload)) | set(upload.vendor_lead_rows.values_list('phone_token', flat=True))
        vendors = {vendor_key(v) for v in upload.vendor_lead_rows.values_list('vendor', flat=True).distinct()}
        if holds.covers(upload.client_id, upload.received_at, tokens, vendors):
            continue  # under a legal hold (Module 14)
        upload.file.delete(save=False)
        UploadedFile.objects.filter(pk=upload.pk).update(file='', purged_at=now)
        count += 1
    return count
