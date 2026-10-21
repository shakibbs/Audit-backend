from celery import shared_task

from apps.clients.models import Client
from apps.tenancy.scope import tenant

from .marks import run


@shared_task
def check_marks() -> int:
    """Every 5 minutes: did the tools mark new opt-outs "do not contact"? Urgent when not, M38 at the deadline."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += run(client)
    return count
