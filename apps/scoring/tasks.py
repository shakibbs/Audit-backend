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
