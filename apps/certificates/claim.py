"""The urgent queue: claim every waiting certificate before its deadline. Runs every minute, before other work."""
from datetime import timedelta

from django.utils import timezone

from apps.access_log.recorder import record
from apps.connections.models import Connection, Status
from apps.ledger.models import ContentKind, SourceGrade
from apps.ledger.record import ledger_job
from apps.tenancy.scope import all_clients, tenant

from . import vendors
from .models import CertificateClaim

ALERT_BEFORE = timedelta(hours=12)  # still not claimed 12 hours before the deadline: say so
PER_RUN = 200
USABLE = [Status.CONNECTED, Status.STALE, Status.UNTESTED]


def key_for(claim: CertificateClaim) -> Connection | None:
    return Connection.objects.filter(client_id=claim.client_id, provider=claim.provider, status__in=USABLE).first()


PHONE_CHECKED: list = []  # callables (claim, phone_token): a phone match answer arrived (results are checked again)


def note_phone(claim: CertificateClaim, token: str, answer: bool | None) -> None:
    if answer is None or not token:
        return
    claim.phone_match = {**(claim.phone_match or {}), token: answer}
    CertificateClaim.objects.filter(pk=claim.pk).update(phone_match=claim.phone_match)
    for receiver in PHONE_CHECKED:
        receiver(claim, token)


def claim_one(claim: CertificateClaim, phone: str | None = None, token: str = '') -> None:
    now = timezone.now()
    if now > claim.deadline_at:
        claim.state = CertificateClaim.State.LOST
        claim.save(update_fields=['state'])
        record('certificate_lost', client_id=claim.client_id, object=str(claim)[:254])
        return
    connection = key_for(claim)
    if connection is None:
        claim.state = CertificateClaim.State.NO_KEY  # stays in the queue: a key added before the deadline still works
        claim.save(update_fields=['state'])
        return
    creds = connection.get_credentials()
    claim.attempts += 1
    try:
        if claim.provider == CertificateClaim.Provider.TRUSTEDFORM:
            facts = vendors.claim_trustedform(claim.cert_ref, creds.get('key', ''), f'civ-client-{claim.client_id}', phone)
        else:
            facts = vendors.read_jornaya(claim.cert_ref, creds.get('account', ''), creds.get('key', ''))
    except vendors.NotFound:
        claim.state = CertificateClaim.State.LOST
        claim.last_error = 'NotFound'
        claim.save(update_fields=['state', 'attempts', 'last_error'])
        record('certificate_lost', client_id=claim.client_id, object=str(claim)[:254])
        return
    except Exception as error:  # vendor down or key refused: retried next minute until the deadline
        claim.last_error = type(error).__name__
        claim.save(update_fields=['attempts', 'last_error'])
        return
    with ledger_job(claim.client, f'{claim.provider} claim') as job:
        job.record(source_system=claim.provider, source_record_id=claim.cert_ref, raw=facts.raw,
                   content_kind=ContentKind.CERTIFICATE, source_grade=SourceGrade.B)
    claim.state, claim.claimed_at, claim.last_error = CertificateClaim.State.CLAIMED, now, ''
    claim.cert_created_at, claim.cert_expires_at, claim.page = facts.created_at, facts.expires_at, vendors.host_and_path(facts.page_url)
    claim.save()
    note_phone(claim, token, facts.phone_match)


def match_now(claim: CertificateClaim, number: str, token: str) -> None:
    """Phone match while the number is still in memory (owner decision A: numbers are never stored). If the provider
    cannot answer now, the match stays "not measured"; the claim itself is retried by the queue as usual."""
    if claim.provider != CertificateClaim.Provider.TRUSTEDFORM or token in (claim.phone_match or {}):
        return  # Jornaya's lead matching is to confirm on a real account
    if claim.state in (CertificateClaim.State.WAITING, CertificateClaim.State.NO_KEY):
        claim_one(claim, phone=number, token=token)
        return
    connection = key_for(claim)
    if claim.state != CertificateClaim.State.CLAIMED or connection is None:
        return
    try:
        note_phone(claim, token, vendors.match_trustedform(claim.cert_ref, connection.get_credentials().get('key', ''), number))
    except Exception:  # provider down or refused: not measured, never retried (the number is gone)
        return


def claim_due() -> int:
    """Waiting certificates, nearest deadline first. Returns how many were tried."""
    with all_clients():
        due = list(CertificateClaim.objects.select_related('client').filter(
            state__in=[CertificateClaim.State.WAITING, CertificateClaim.State.NO_KEY]).order_by('deadline_at')[:PER_RUN])
    for claim in due:
        with tenant(claim.client):
            claim_one(claim)
    warn_close_deadlines()
    return len(due)


def warn_close_deadlines() -> None:
    soon = timezone.now() + ALERT_BEFORE
    with all_clients():
        for claim in CertificateClaim.objects.filter(state__in=[CertificateClaim.State.WAITING, CertificateClaim.State.NO_KEY],
                                                     deadline_at__lte=soon, deadline_alerted=False):
            record('certificate_deadline_close', client_id=claim.client_id, object=str(claim)[:254])
            CertificateClaim.objects.filter(pk=claim.pk).update(deadline_alerted=True)
