from celery import shared_task

from apps.tenancy.scope import all_clients

from .capture import capture_due, purge_old


@shared_task
def capture_pages() -> int:
    """Runs only in the capture container (queue "capture"), where Chromium is installed."""
    return capture_due()


@shared_task
def purge_old_captures() -> int:
    with all_clients():
        return purge_old()
