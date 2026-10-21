from celery import shared_task

from apps.tenancy.scope import all_clients

from .contracts import purge_old


@shared_task
def purge_old_contracts() -> int:
    """Nightly: contract files older than 4 years are deleted; their fingerprints stay."""
    with all_clients():
        return purge_old()
