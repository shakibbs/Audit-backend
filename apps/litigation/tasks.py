from celery import shared_task

from .webrecon import refresh


@shared_task
def read_webrecon() -> int:
    """Weekly: WebRecon's new monthly litigation posts."""
    return refresh()
