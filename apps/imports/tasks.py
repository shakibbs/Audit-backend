from celery import shared_task

from .batches import rebuild_all


@shared_task
def rebuild_batches() -> None:
    from .dialer_lists import read_all
    read_all()  # numbers put into dialer lists since last time (Vicidial, Convoso)
    rebuild_all()
    from apps.clients.models import Client
    from apps.provenance.requests import send
    from apps.tenancy.scope import tenant
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            send(client)  # proof requests for uploaded lists not sampled yet
