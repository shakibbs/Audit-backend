from celery import shared_task

from .batches import rebuild_all


@shared_task
def rebuild_batches() -> None:
    rebuild_all()
