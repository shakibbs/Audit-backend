from celery import shared_task
from django.utils import timezone

from apps.clients.models import Client
from apps.tenancy.scope import all_clients, tenant

from .make import last_month, latest_or_make, purge_old


@shared_task
def monthly_reports() -> int:
    """On the 6th (after the month locks): last month's audit report for every client; reports older than 4 years go."""
    period, made = last_month(timezone.localdate()), 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            made += latest_or_make(client, period, 'CiV (automatic)') is not None
    with all_clients():
        purge_old()
    return made
