from celery import shared_task

from .check import check_recent


@shared_task
def check_completeness() -> None:
    check_recent()
