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


def claim_one(claim: CertificateClaim) -> None:
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
            facts = vendors.claim_trustedform(claim.cert_ref, creds.get('key', ''), f'civ-client-{claim.client_id}')
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
