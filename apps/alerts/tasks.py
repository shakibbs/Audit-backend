from celery import shared_task

from apps.clients.models import Client
from apps.tenancy.scope import tenant

from .raise_ import refresh


@shared_task
def raise_alerts() -> int:
    """Every 5 minutes: gather what needs a look into alerts (portal only)."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += refresh(client)
    return count
