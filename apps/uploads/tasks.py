from celery import shared_task

from apps.tenancy.scope import all_clients

from .effects import purge_old


@shared_task
def purge_old_uploads() -> int:
    with all_clients():
        return purge_old()
