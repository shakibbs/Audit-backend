from celery import shared_task
from django.utils import timezone

from apps.buyers.attestation import save as save_attestation
from apps.clients.models import Client
from apps.findings.build import refresh
from apps.tenancy.scope import tenant
from apps.vendors.score import save_month

from .snapshots import run_nightly


@shared_task
def snapshot_metrics() -> int:
    """Nightly at 04:00 UTC: save every client's metrics for the open months (locked months re-checked on Sundays),
    the vendor scorecards, then update its findings."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += run_nightly(client)
            save_month(client)  # Module 12: this month's vendor scorecards
            refresh(client)  # Module 11: the findings from the newly saved month
            save_attestation(client, timezone.localdate().replace(day=1))  # Module 15: this month's risk attestation
    return count


@shared_task
def refresh_one(client_id: int) -> None:
    """Right after an upload (owner, 2026-10-24): this client's open month, vendor scorecards, findings, risk
    attestation and alerts are worked out again within minutes, instead of waiting for the 04:00 run."""
    from apps.alerts.raise_ import refresh as refresh_alerts
    from .snapshots import snapshot
    client = Client.objects.filter(pk=client_id, is_active=True).first()
    if client is None:
        return
    try:
        with tenant(client):
            month = timezone.localdate().replace(day=1)
            snapshot(client, month)
            save_month(client)
            refresh(client)
            save_attestation(client, month)
            refresh_alerts(client)
    finally:
        Client.objects.filter(pk=client_id).update(refresh_pending_since=None)


REFRESH_DELAY_SECONDS = 60  # several uploads in a row share one re-run


def queue_refresh(client) -> None:
    """Asks for a re-run of this client's month; one already waiting covers it."""
    from datetime import timedelta
    now = timezone.now()
    waiting = Client.objects.filter(pk=client.pk, refresh_pending_since__gt=now - timedelta(minutes=15)).exists()
    if waiting:
        return
    Client.objects.filter(pk=client.pk).update(refresh_pending_since=now)
    from django.db import transaction
    transaction.on_commit(lambda: refresh_one.apply_async((client.pk,), countdown=REFRESH_DELAY_SECONDS))

