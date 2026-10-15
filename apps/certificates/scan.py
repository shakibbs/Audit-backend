"""Finds certificate links and tokens in every synced record (lead, call, CRM row) and queues them to be claimed."""
import re
from datetime import timedelta

from django.db import IntegrityError, transaction

from .models import CertificateClaim

TRUSTEDFORM = re.compile(r'https?://cert\.trustedform\.com/([0-9a-f]{40})', re.I)
# Jornaya LeadiD tokens are UUIDs; only taken from fields named for Jornaya / LeadiD, never any UUID.
JORNAYA = re.compile(r'(?i)(?:leadid_token|leadid|lead_id_token|universal_leadid|jornaya[a-z_]*)["\']?\s*[:=]\s*["\']?'
                     r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')
UNRETAINED_HOURS = 72  # Rulebook cert_unretained_expiry_hours; read from the Rulebook when it is loaded


def window_hours() -> int:
    from django.utils import timezone

    from apps.rulebook.lookup import NoRulebook, RuleSet
    try:
        return RuleSet().get('cert_unretained_expiry_hours', on=timezone.localdate()).value or UNRETAINED_HOURS
    except NoRulebook:
        return UNRETAINED_HOURS


def found_in(raw: bytes) -> list[tuple[str, str]]:
    text = raw.decode('utf-8', errors='ignore')
    found = [('trustedform', m.lower()) for m in TRUSTEDFORM.findall(text)]
    found += [('jornaya', m.upper()) for m in JORNAYA.findall(text)]
    return list(dict.fromkeys(found))


def scan_record(client, connection, record, phone_tokens) -> None:
    """A hand-off receiver: queues each certificate seen in the record (once per client)."""
    found = found_in(record.raw)
    if not found:
        return
    deadline = record.changed_at + timedelta(hours=window_hours())
    for provider, ref in found:
        try:
            with transaction.atomic():
                CertificateClaim.objects.create(client=client, provider=provider, cert_ref=ref, deadline_at=deadline)
        except IntegrityError:
            pass  # already queued
