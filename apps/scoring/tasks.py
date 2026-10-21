from celery import shared_task

from apps.clients.models import Client
from apps.tenancy.scope import tenant

from .snapshots import run_nightly


@shared_task
def snapshot_metrics() -> int:
    """Nightly at 04:00 UTC: save every client's metrics for the open months (locked months re-checked on Sundays)."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += run_nightly(client)
    return count
