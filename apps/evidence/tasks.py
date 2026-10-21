from celery import shared_task

from apps.clients.models import Client
from apps.tenancy.scope import tenant

from .refetch import weekly_sample


@shared_task
def weekly_refetch() -> int:
    """Sundays: 50 sealed call and text records per client asked for again and compared with what CiV saw."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += weekly_sample(client)
    return count
