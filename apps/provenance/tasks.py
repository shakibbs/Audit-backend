from celery import shared_task

from apps.clients.models import Client
from apps.tenancy.scope import tenant

from .ladder import rebuild


@shared_task
def rebuild_provenance() -> int:
    """Every 30 minutes, each client: where each contacted number came from."""
    count = 0
    for client in Client.objects.filter(is_active=True):
        with tenant(client):
            count += rebuild(client)
    return count


@shared_task
def purge_old_proof_files() -> int:
    from apps.tenancy.scope import all_clients

    from .requests import purge_old
    with all_clients():
        return purge_old()
