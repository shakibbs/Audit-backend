from celery import shared_task

from apps.clients.models import Client
from apps.findings.build import refresh
from apps.tenancy.scope import tenant

from .snapshots import run_nightly


@shared_task
def snapshot_metrics() -> int:
    """Nightly at 04:00 UTC: save every client's metrics for the open months (locked months re-checked on Sundays),
    then update its findings."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += run_nightly(client)
            refresh(client)  # Module 11: the findings from the newly saved month
    return count
